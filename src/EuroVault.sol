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

    constructor(address oracleAddress, address eurcAddress) {
        operator = msg.sender;
        oracle = IEurAoaOracle(oracleAddress);
        eurc = IERC20(eurcAddress);
        spreadBps = 100; // 1%
    }

    function depositLiquidity(uint256 amount) public {
        require(msg.sender == operator, "Not authorized");
        require(eurc.transferFrom(msg.sender, address(this), amount), "Transfer failed");
    }

    function withdrawLiquidity(address to, uint256 amount) public {
        require(msg.sender == operator, "Not authorized");
        require(to != address(0), "Invalid address");
        require(amount <= availableLiquidity(), "Insufficient liquidity");

        require(eurc.transfer(to, amount), "Transfer failed");
    }

    function availableLiquidity() public view returns (uint256) {
        return eurc.balanceOf(address(this)) - totalLiabilities;
    }

    function creditFromKwanza(uint256 userId, uint256 aoaCents, bytes32 ref) public {
        require(msg.sender == operator, "Not authorized");
        _useRef(ref);

        uint256 rate = oracle.latestRate();
        uint256 gross = aoaCents * 1e12 / rate;
        uint256 fee = gross * spreadBps / 10000;
        uint256 net = gross - fee;

        require(availableLiquidity() >= net, "Insufficient liquidity");

        balanceOf[userId] += net;
        totalLiabilities += net;
        totalFeesCollected += fee;
    }

    function payout(uint256 userId, uint256 amount, address to, bytes32 ref) public {
        require(msg.sender == operator, "Not authorized");
        _useRef(ref);
        require(balanceOf[userId] >= amount, "Insufficient balance");

        balanceOf[userId] -= amount;
        totalLiabilities -= amount;

        require(eurc.transfer(to, amount), "Transfer failed");
    }

    function setSpread(uint256 newSpreadBps) public {
        require(msg.sender == operator, "Not authorized");
        require(newSpreadBps <= MAX_SPREAD_BPS, "Spread too high");
        spreadBps = newSpreadBps;
    }

    function _useRef(bytes32 ref) internal {
        require(ref != bytes32(0), "Invalid ref");
        require(!processedRefs[ref], "Ref already processed");
        processedRefs[ref] = true;
    }
}
