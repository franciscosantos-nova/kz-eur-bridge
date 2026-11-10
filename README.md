# kz-eur-bridge

**Stablecoin settlement layer for the Portugal ↔ Angola remittance corridor.**

An Angolan family pays in kwanzas through a local rail (Multicaixa / KWiK). Their balance is held in euros (EURC) on-chain, at the official BNA rate plus a transparent margin. From there they can pay with a card in Portugal, send money to a bank account in Europe, or transfer to another user, such as a student in Lisbon, for free.

The kwanza never touches the blockchain. It stays with a licensed Angolan partner; the smart contracts handle the euro side: pricing, custody, accounting and payouts.

> ⚠️ Testnet prototype built as a learning and portfolio project. Not audited. Not for real funds.

---

## The problem

- The kwanza is not freely convertible, and euros are scarce in Angola.
- Sending money from Angola to Portugal means bank fees plus a large FX markup. In early conversations with Angolan families in Lisbon, one reported paying **€40+ in fees per transfer**, on top of an unfavourable rate.
- Informal USDT/AOA P2P markets already exist, which shows the demand, but they are unregulated and risky.

## How it works

```
Parent in Luanda pays 50,000 kz (Multicaixa)      ← off-chain, at the Angolan partner
        │
        ▼
backend → EuroVault.creditFromKwanza()
        │   rate from EurAoaOracle: 1,065.50 AOA/EUR
        │   gross 46.93 € − 1% margin (0.47 €) = 46.46 € balance
        ▼
EUR balance ──► payout()                → card payment / SEPA transfer in Portugal
            └─► transferBetweenUsers()  → child in Lisbon (free, no tokens move)
```

## Contracts

| Contract | Responsibility |
|---|---|
| [`EurAoaOracle`](src/EurAoaOracle.sol) | Publishes the EUR/AOA rate (8 decimals). Only the authorised updater can write. Rejects moves above 5% per update and refuses to serve a rate older than 4 days. |
| [`EuroVault`](src/EuroVault.sol) | Custodial EURC vault. Converts kwanza payments into euro balances, applies the margin, pays out, and keeps itself solvent at all times. |
| [`MockEURC`](src/MockEURC.sol) | 6-decimal ERC-20 used as test EURC. Testnet only. |

### Deployed on Base Sepolia (verified)

| Contract | Address |
|---|---|
| EuroVault | [`0xFCEc6aEC8122b6bA354660775A1bbfb6D75BE667`](https://sepolia.basescan.org/address/0xFCEc6aEC8122b6bA354660775A1bbfb6D75BE667#code) |
| EurAoaOracle | [`0x9df9136c68418Ae58eB1e811378711D0b6484871`](https://sepolia.basescan.org/address/0x9df9136c68418Ae58eB1e811378711D0b6484871#code) |
| MockEURC | [`0x365B275eB4688B88c2bf60cAF64B5550074E7F3A`](https://sepolia.basescan.org/address/0x365B275eB4688B88c2bf60cAF64B5550074E7F3A#code) |

Open the vault on Basescan → **Contract → Read Contract** and call `quote(5000000)` to price 50,000 kz.

## Design decisions

**Solvency invariant.** `EURC held by the vault ≥ totalLiabilities` at all times. Credits only proceed if there is free liquidity, and the treasury can only withdraw what does not belong to customers. Fuzz tests check this after random credits, payouts and withdrawals.

**Convert on top-up, not on spend.** Once kwanzas are paid in, the customer's balance is in euros and stops losing value to kwanza depreciation. It also means a single FX conversion per euro spent in Portugal, versus USD-denominated crypto cards that charge a second FX fee on every EUR purchase.

**The contract computes, the backend reports.** The backend only says "user X paid Y kwanzas". The vault prices it with the oracle, so a compromised or buggy backend cannot credit arbitrary euro amounts.

**Idempotency.** Every credit, payout and transfer carries a unique reference (for example the Multicaixa reference). Retrying after a network error can never credit or pay twice. A reverted operation does not consume its reference.

**Slippage protection.** The user accepts a quoted amount (`minNet`). If the rate moves against them before execution, the credit reverts instead of silently paying less.

**Bounded margin.** `MAX_SPREAD_BPS = 500` is a `constant`: not even the operator can charge more than 5%.

**Oracle safety.** No Chainlink feed exists for EUR/AOA, so the oracle is custom. A deviation cap stops typos and attacks; a staleness check stops the vault from converting at an outdated rate. An official devaluation would require a deliberate redeploy or an admin path (see roadmap).

**Checks-effects-interactions.** State and events are updated before any external token call. Custom errors and an `onlyOperator` modifier keep the code cheaper and the access rules visible in every function signature.

## Tests

40 tests, including 4 fuzz tests.

```bash
forge test
forge test --match-test testFuzz --fuzz-runs 10000
forge coverage
forge test --gas-report
```

| Area | What is tested |
|---|---|
| Oracle | access control, deviation up and down, staleness, zero rate, events |
| Credits | conversion maths, margin, liquidity limits, stale oracle propagation |
| Quotes | exact quote, rate moving against / in favour of the user |
| Idempotency | reused references on credits and payouts, empty refs, reverted credits not burning refs |
| Treasury | profit withdrawal, never touching customer funds |
| Transfers | balances, conservation of total liabilities, self-transfer |
| Events | every state-changing operation emits the expected event |
| Fuzz | solvency after credits, payouts and withdrawals; conservation on transfers |

### Gas (optimizer on, 200 runs)

| Operation | Avg gas |
|---|---|
| `creditFromKwanza` | ~136k |
| `payout` | ~93k |
| `transferBetweenUsers` | ~76k |
| `quote` (view) | ~15k, free off-chain |

Full deployment of the three contracts cost about 0.000011 ETH on Base Sepolia. Most per-call cost comes from storage writes (reference + balance), which is why Base, an L2, is a requirement for the business model: margins are cents per transfer.

## Run it locally

Requires [Foundry](https://book.getfoundry.sh/).

```bash
git clone <this repo> --recurse-submodules
cd kz-eur-bridge
forge build
forge test
```

### Deploy to Base Sepolia

```bash
cp .env.example .env            # add your ETHERSCAN_API_KEY
cast wallet import deployer --interactive
set -a; source .env; set +a

forge script script/Deploy.s.sol --rpc-url base_sepolia \
  --account deployer --sender <your-address> --broadcast --verify
```

### Interact with `cast`

```bash
VAULT=0xFCEc6aEC8122b6bA354660775A1bbfb6D75BE667

# Price 50,000 kz (free)
cast call $VAULT "quote(uint256)(uint256,uint256,uint256)" 5000000 --rpc-url base_sepolia

# Credit user 1 (operator only)
cast send $VAULT "creditFromKwanza(uint256,uint256,uint256,bytes32)" \
  1 5000000 0 $(cast format-bytes32-string "MCX-0001") \
  --rpc-url base_sepolia --account deployer
```

The oracle refuses rates older than 4 days, so on the testnet `updateRate` has to be called periodically. In production this is the job of an automated service reading the BNA reference rate.

## Known limitations

- **Centralised trust.** A single operator key controls credits, payouts and the margin, and a single updater controls the rate. Production would need role separation, multisig and timelocks.
- **Custodial.** Users have no wallet; balances are internal accounting keyed by user ID.
- **No pause switch yet**, and no admin path to handle an official devaluation above the 5% cap.
- **User IDs are plain integers.** They should be hashed internal IDs so balances cannot be linked to people.
- **Mock token.** Uses MockEURC instead of Circle's EURC.
- **`totalFeesCollected` is stored on-chain**, costing ~5k gas per credit; it could be derived off-chain from events.

## Regulatory context

The design assumes licensed partners on both sides: an e-money / payment institution in Portugal (MiCA-compliant EURC on the EU side) and a BNA-licensed bank or wallet in Angola for the kwanza leg, where every FX operation by a resident is subject to annual limits and reporting. Per-operation references and events make every movement traceable for that reporting; enforcing per-user annual limits on-chain is on the roadmap.

## Roadmap

- [ ] Pause switch and role separation (operator, treasury, rate updater)
- [ ] Hashed user IDs
- [ ] Per-user annual limits mirroring BNA rules
- [ ] Invariant tests (random sequences of operations)
- [ ] Rate-updater service reading the BNA reference rate
- [ ] Backend integrating a Multicaixa/KWiK sandbox
- [ ] Portugal → Angola direction and netting of opposite flows
- [ ] Swap MockEURC for Circle's test EURC
