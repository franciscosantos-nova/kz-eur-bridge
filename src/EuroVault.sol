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

    constructor(address oracleAddress, address eurcAddress) {
        operator = msg.sender;
        oracle = IEurAoaOracle(oracleAddress);
        eurc = IERC20(eurcAddress);
    }

    function depositLiquidity(uint256 amount) public {
        require(msg.sender == operator, "Not authorized");
        require(eurc.transferFrom(msg.sender, address(this), amount), "Transfer failed");
    }

    function availableLiquidity() public view returns (uint256) {
        return eurc.balanceOf(address(this)) - totalLiabilities;
    }

    function creditFromKwanza(uint256 userId, uint256 aoaCents) public {
        require(msg.sender == operator, "Not authorized");
        uint256 rate = oracle.latestRate();
        uint256 euros = aoaCents * 1e12 / rate;

        require(availableLiquidity() >= euros, "Insufficient liquidity");

        balanceOf[userId] += euros;
        totalLiabilities += euros;
    }

    function payout(uint256 userId, uint256 amount, address to) public {
        require(msg.sender == operator, "Not authorized");
        require(balanceOf[userId] >= amount, "Insufficient balance");

        balanceOf[userId] -= amount;
        totalLiabilities -= amount;

        require(eurc.transfer(to, amount), "Transfer failed");
    }
}