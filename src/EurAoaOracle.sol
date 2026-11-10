// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract EurAoaOracle {
    uint256 private rate;
    uint256 public updatedAt;
    address public updater;
    uint256 public maxDeviationBps;
    uint256 public maxAge;

    constructor(uint256 initialRate) {
        require(initialRate > 0, "Rate cannot be zero");
        updater = msg.sender;
        maxDeviationBps = 500;
        maxAge = 4 days;
        rate = initialRate;
        updatedAt = block.timestamp;
    }

    function updateRate(uint256 newRate) public {
        require(msg.sender == updater, "Not authorized");
        uint256 diff;
        if (newRate > rate) {
            diff = newRate - rate;
        } else {
            diff = rate - newRate;
        }

        require(diff * 10000 <= rate * maxDeviationBps, "Deviation too high");

        rate = newRate;
        updatedAt = block.timestamp;
    }

    function latestRate() public view returns (uint256) {
        require(block.timestamp <= updatedAt + maxAge, "Stale rate");
        return rate;
    }
}
