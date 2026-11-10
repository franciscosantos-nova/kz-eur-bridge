// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface IEurAoaOracle {
    function latestRate() external view returns (uint256);
}

contract EuroVault {
    address public operator;
    mapping(uint256 => uint256) public balanceOf;
    IEurAoaOracle public oracle;
    IERC20 public eurc;
    uint256 public totalLiabilities;
    uint256 public constant MAX_SPREAD_BPS = 500;
    uint256 public spreadBps;
    uint256 public totalFeesCollected;
    mapping(bytes32 => bool) public processedRefs;

    // ---------- Eventos ----------

    event LiquidityDeposited(address indexed from, uint256 amount);
    event LiquidityWithdrawn(address indexed to, uint256 amount);
    event KwanzaCredited(
        uint256 indexed userId, bytes32 indexed ref, uint256 aoaCents, uint256 gross, uint256 fee, uint256 net
    );
    event Payout(uint256 indexed userId, bytes32 indexed ref, address indexed to, uint256 amount);
    event InternalTransfer(uint256 indexed fromUser, uint256 indexed toUser, bytes32 indexed ref, uint256 amount);
    event SpreadUpdated(uint256 oldSpreadBps, uint256 newSpreadBps);

    // ---------- Erros ----------

    error NotAuthorized();
    error InvalidAddress();
    error InvalidRef();
    error RefAlreadyProcessed(bytes32 ref);
    error SameUser();
    error SpreadTooHigh(uint256 spreadBps);
    error Slippage(uint256 net, uint256 minNet);
    error InsufficientLiquidity(uint256 available, uint256 needed);
    error InsufficientBalance(uint256 balance, uint256 needed);
    error TransferFailed();

    // ---------- Modifiers ----------

    modifier onlyOperator() {
        if (msg.sender != operator) revert NotAuthorized();
        _;
    }

    constructor(address oracleAddress, address eurcAddress) {
        operator = msg.sender;
        oracle = IEurAoaOracle(oracleAddress);
        eurc = IERC20(eurcAddress);
        spreadBps = 100; // 1%
    }

    // ---------- Liquidez ----------

    function depositLiquidity(uint256 amount) public onlyOperator {
    emit LiquidityDeposited(msg.sender, amount);

    if (!eurc.transferFrom(msg.sender, address(this), amount)) revert TransferFailed();
    }

    function withdrawLiquidity(address to, uint256 amount) public onlyOperator {
    if (to == address(0)) revert InvalidAddress();
    uint256 available = availableLiquidity();
    if (amount > available) revert InsufficientLiquidity(available, amount);

    emit LiquidityWithdrawn(to, amount);

    if (!eurc.transfer(to, amount)) revert TransferFailed();
    }

    function availableLiquidity() public view returns (uint256) {
        return eurc.balanceOf(address(this)) - totalLiabilities;
    }

    // ---------- Cotação ----------

    function quote(uint256 aoaCents) public view returns (uint256 gross, uint256 fee, uint256 net) {
        uint256 rate = oracle.latestRate();
        gross = aoaCents * 1e12 / rate;
        // O erro de arredondamento é < 1 unidade de EURC e favorece o cliente.
        // forge-lint: disable-next-line(divide-before-multiply)
        fee = gross * spreadBps / 10000;
        
        net = gross - fee;
    }

    // ---------- Operações do cliente ----------

    function creditFromKwanza(uint256 userId, uint256 aoaCents, uint256 minNet, bytes32 ref) public onlyOperator {
        _useRef(ref);

        (uint256 gross, uint256 fee, uint256 net) = quote(aoaCents);

        if (net < minNet) revert Slippage(net, minNet);
        uint256 available = availableLiquidity();
        if (available < net) revert InsufficientLiquidity(available, net);

        balanceOf[userId] += net;
        totalLiabilities += net;
        totalFeesCollected += fee;

        emit KwanzaCredited(userId, ref, aoaCents, gross, fee, net);
    }

    function payout(uint256 userId, uint256 amount, address to, bytes32 ref) public onlyOperator {
    _useRef(ref);
    _debit(userId, amount);
    totalLiabilities -= amount;

    emit Payout(userId, ref, to, amount);

    if (!eurc.transfer(to, amount)) revert TransferFailed();
    }
    function transferBetweenUsers(uint256 fromUser, uint256 toUser, uint256 amount, bytes32 ref)
        public
        onlyOperator
    {
        if (fromUser == toUser) revert SameUser();
        _useRef(ref);
        _debit(fromUser, amount);
        balanceOf[toUser] += amount;

        emit InternalTransfer(fromUser, toUser, ref, amount);
    }

    // ---------- Administração ----------

    function setSpread(uint256 newSpreadBps) public onlyOperator {
    if (newSpreadBps > MAX_SPREAD_BPS) revert SpreadTooHigh(newSpreadBps);

    uint256 oldSpreadBps = spreadBps;
    spreadBps = newSpreadBps;

    emit SpreadUpdated(oldSpreadBps, newSpreadBps);
}

    // ---------- Internas ----------

    function _useRef(bytes32 ref) internal {
        if (ref == bytes32(0)) revert InvalidRef();
        if (processedRefs[ref]) revert RefAlreadyProcessed(ref);
        processedRefs[ref] = true;
    }

    function _debit(uint256 userId, uint256 amount) internal {
        uint256 balance = balanceOf[userId];
        if (balance < amount) revert InsufficientBalance(balance, amount);
        balanceOf[userId] = balance - amount;
    }
}