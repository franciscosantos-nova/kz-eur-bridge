"""Ligação só-de-leitura aos contratos do kz-eur-bridge na Base Sepolia.

Isola toda a lógica de web3.py, ABIs e conversão de unidades,
para que app.py só peça "dá-me a cotação" ou "dá-me o estado do cofre"
sem saber nada sobre Solidity, decimais ou erros de RPC.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import requests
from dotenv import load_dotenv
from eth_abi import decode as abi_decode
from web3 import Web3
from web3.exceptions import ContractLogicError

load_dotenv()

_ABI_DIR = Path(__file__).resolve().parent.parent / "abi"

# Endereços e RPC têm valores por omissão: são contratos públicos e
# verificados numa testnet, não há nada secreto a proteger aqui. O .env
# só serve para poderes apontar para outro RPC ou outro deploy sem tocar no código.
RPC_URL = os.getenv("RPC_URL", "https://sepolia.base.org")
VAULT_ADDRESS = os.getenv("VAULT_ADDRESS", "0xaF01ae066ce87DB2cca972126E2371972a746C4f")
ORACLE_ADDRESS = os.getenv("ORACLE_ADDRESS", "0xB8dcA382cd3011551e0fce10e32c1d58d499E570")
EURC_ADDRESS = os.getenv("EURC_ADDRESS", "0x808456652fdb597867f38412077A9182bf77359F")

BASESCAN_ADDRESS_URL = "https://sepolia.basescan.org/address/"

AOA_CENTS_DECIMALS = 2
ORACLE_RATE_DECIMALS = 8
EURC_DECIMALS = 6


# ---------- Erros próprios ----------


class StaleRateError(Exception):
    """A taxa do oráculo está desatualizada (custom error StaleRate)."""

    def __init__(self, last_update: int, max_age: int):
        self.last_update = last_update
        self.max_age = max_age
        super().__init__("A taxa do oráculo está desatualizada.")


class RpcConnectionError(Exception):
    """Não foi possível ligar ao nó RPC."""


class InvalidAmountError(Exception):
    """O montante introduzido pelo utilizador não é válido."""


# ---------- Conversão de unidades (puras, sem rede) ----------


def cents_to_kz(cents: int) -> Decimal:
    """Cêntimos de kwanza (2 casas decimais) para kwanzas."""
    return Decimal(cents) / Decimal(10**AOA_CENTS_DECIMALS)


def micro_to_eur(micro: int) -> Decimal:
    """Unidades de EURC (6 casas decimais) para euros."""
    return Decimal(micro) / Decimal(10**EURC_DECIMALS)


def raw_rate_to_decimal(raw: int) -> Decimal:
    """Taxa crua do oráculo (8 casas decimais) para AOA/EUR."""
    return Decimal(raw) / Decimal(10**ORACLE_RATE_DECIMALS)


def _format_pt(value: Decimal, decimals: int = 2, thousands: bool = True) -> str:
    """Formata um Decimal à portuguesa: '.' nos milhares, ',' nos decimais."""
    spec = f",.{decimals}f" if thousands else f".{decimals}f"
    formatted = format(value, spec)
    integer_part, _, decimal_part = formatted.partition(".")
    if thousands:
        integer_part = integer_part.replace(",", ".")
    return f"{integer_part},{decimal_part}" if decimal_part else integer_part


def format_kz(cents: int) -> str:
    return f"{_format_pt(cents_to_kz(cents))} kz"


def format_eur(micro: int) -> str:
    return f"{_format_pt(micro_to_eur(micro))} €"


def format_rate(raw: int) -> str:
    """Sem separador de milhares: '1065,50', como aparece numa cotação cambial."""
    return _format_pt(raw_rate_to_decimal(raw), thousands=False)


def parse_kz_input(text: str) -> int:
    """Converte o texto escrito pelo utilizador (kwanzas) em cêntimos (int).

    Aceita tanto '50000' como o formato português '50.000,50'.
    """
    cleaned = text.strip().replace(" ", "")
    if not cleaned:
        raise InvalidAmountError("Indica um montante em kwanzas.")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise InvalidAmountError("Esse montante não é um número válido.") from exc
    if value <= 0:
        raise InvalidAmountError("O montante tem de ser superior a zero.")
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def humanize_seconds_ago(seconds: int) -> str:
    """'há 2 horas', 'há 3 dias', etc."""
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return "há instantes"
    minutes = seconds // 60
    if minutes < 60:
        return f"há {minutes} minuto{'s' if minutes != 1 else ''}"
    hours = seconds // 3600
    if hours < 24:
        return f"há {hours} hora{'s' if hours != 1 else ''}"
    days = seconds // 86400
    return f"há {days} dia{'s' if days != 1 else ''}"


# ---------- Ligação à blockchain ----------


def _load_abi(filename: str) -> list:
    with open(_ABI_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def _get_web3() -> Web3:
    return Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 10}))


def _get_vault(w3: Web3):
    abi = _load_abi("EuroVault.json")
    return w3.eth.contract(address=Web3.to_checksum_address(VAULT_ADDRESS), abi=abi)


def _get_oracle(w3: Web3):
    abi = _load_abi("EurAoaOracle.json")
    return w3.eth.contract(address=Web3.to_checksum_address(ORACLE_ADDRESS), abi=abi)


# Selector calculado em runtime (primeiros 4 bytes do keccak da assinatura),
# para não andar a copiar hashes mágicos sem explicação no código.
_STALE_RATE_SELECTOR = Web3.keccak(text="StaleRate(uint256,uint256)")[:4]


def _decode_stale_rate(data: str | None) -> StaleRateError | None:
    """Se 'data' for o revert do custom error StaleRate, devolve-o decodificado."""
    if not data:
        return None
    hex_data = data[2:] if data.startswith("0x") else data
    try:
        raw = bytes.fromhex(hex_data)
    except ValueError:
        return None
    if raw[:4] != _STALE_RATE_SELECTOR:
        return None
    last_update, max_age = abi_decode(["uint256", "uint256"], raw[4:])
    return StaleRateError(last_update, max_age)


def _call(fn):
    """Executa uma chamada de leitura, traduzindo os erros do contrato e do RPC."""
    try:
        return fn.call()
    except ContractLogicError as exc:
        stale = _decode_stale_rate(exc.data if isinstance(exc.data, str) else None)
        if stale is not None:
            raise stale from exc
        raise
    except requests.exceptions.RequestException as exc:
        raise RpcConnectionError("Não foi possível ligar ao nó RPC.") from exc


def max_aoa_cents_for_liquidity(available_liquidity_micro: int, rate_raw: int, spread_bps: int) -> int:
    """Maior aoaCents cujo quote().net cabe na liquidez disponível.

    quote() faz, em cêntimos/wei inteiros: gross = aoaCents*1e12 // rate;
    net = gross - gross*spreadBps//10000. Invertendo essa conta (sem os
    arredondamentos por defeito do Solidity) dá sempre um valor igual ou
    ligeiramente abaixo do que o contrato aceitaria, nunca acima — por
    isso serve como um máximo seguro para mostrar ao utilizador.
    """
    denom = (10_000 - spread_bps) * 10**12
    if denom <= 0 or available_liquidity_micro <= 0:
        return 0
    return (available_liquidity_micro * rate_raw * 10_000) // denom


@dataclass
class Quote:
    gross_micro: int
    fee_micro: int
    net_micro: int
    available_liquidity_micro: int
    rate_raw: int
    spread_bps: int

    @property
    def gross_str(self) -> str:
        return format_eur(self.gross_micro)

    @property
    def fee_str(self) -> str:
        return format_eur(self.fee_micro)

    @property
    def net_str(self) -> str:
        return format_eur(self.net_micro)

    @property
    def has_sufficient_liquidity(self) -> bool:
        return self.net_micro <= self.available_liquidity_micro

    @property
    def max_kz_str(self) -> str:
        max_cents = max_aoa_cents_for_liquidity(
            self.available_liquidity_micro, self.rate_raw, self.spread_bps
        )
        return format_kz(max_cents)


def get_quote(aoa_cents: int) -> Quote:
    """Chama EuroVault.quote(aoaCents) e lê a liquidez disponível para a comparar.

    Pode lançar StaleRateError ou RpcConnectionError.
    """
    w3 = _get_web3()
    vault = _get_vault(w3)
    oracle = _get_oracle(w3)
    gross, fee, net = _call(vault.functions.quote(aoa_cents))
    available = _call(vault.functions.availableLiquidity())
    spread_bps = _call(vault.functions.spreadBps())
    rate_raw = _call(oracle.functions.latestRate())
    return Quote(
        gross_micro=gross,
        fee_micro=fee,
        net_micro=net,
        available_liquidity_micro=available,
        rate_raw=rate_raw,
        spread_bps=spread_bps,
    )


@dataclass
class VaultSnapshot:
    available_liquidity_micro: int
    total_liabilities_micro: int
    total_fees_collected_micro: int
    spread_bps: int
    max_spread_bps: int
    oracle_updated_at: int
    oracle_max_age: int
    current_rate_raw: int | None  # None quando a taxa está desatualizada
    rate_is_stale: bool

    @property
    def available_liquidity_str(self) -> str:
        return format_eur(self.available_liquidity_micro)

    @property
    def total_liabilities_str(self) -> str:
        return format_eur(self.total_liabilities_micro)

    @property
    def total_fees_collected_str(self) -> str:
        return format_eur(self.total_fees_collected_micro)

    @property
    def spread_pct_str(self) -> str:
        return _format_pt(Decimal(self.spread_bps) / 100, thousands=False)

    @property
    def max_spread_pct_str(self) -> str:
        return _format_pt(Decimal(self.max_spread_bps) / 100, thousands=False)

    @property
    def current_rate_str(self) -> str | None:
        return format_rate(self.current_rate_raw) if self.current_rate_raw is not None else None


def get_vault_snapshot() -> VaultSnapshot:
    """Lê o estado atual do cofre e do oráculo para o painel 'ao vivo'."""
    w3 = _get_web3()
    vault = _get_vault(w3)
    oracle = _get_oracle(w3)

    available = _call(vault.functions.availableLiquidity())
    liabilities = _call(vault.functions.totalLiabilities())
    fees = _call(vault.functions.totalFeesCollected())
    spread = _call(vault.functions.spreadBps())
    max_spread = _call(vault.functions.MAX_SPREAD_BPS())
    updated_at = _call(oracle.functions.updatedAt())
    max_age = _call(oracle.functions.maxAge())

    rate_raw: int | None = None
    is_stale = False
    try:
        rate_raw = _call(oracle.functions.latestRate())
    except StaleRateError:
        is_stale = True

    return VaultSnapshot(
        available_liquidity_micro=available,
        total_liabilities_micro=liabilities,
        total_fees_collected_micro=fees,
        spread_bps=spread,
        max_spread_bps=max_spread,
        oracle_updated_at=updated_at,
        oracle_max_age=max_age,
        current_rate_raw=rate_raw,
        rate_is_stale=is_stale,
    )
