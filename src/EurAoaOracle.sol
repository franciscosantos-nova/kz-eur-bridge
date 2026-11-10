// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract EurAoaOracle {
    uint256 private rate;
    uint256 public updatedAt;
    address public updater;
    uint256 public maxDeviationBps;
    uint256 public maxAge;

    // ---------- Eventos ----------

    event RateUpdated(uint256 oldRate, uint256 newRate, uint256 timestamp);

    // ---------- Erros ----------

    error NotAuthorized();
    error RateCannotBeZero();
    error DeviationTooHigh(uint256 oldRate, uint256 newRate);
    error StaleRate(uint256 lastUpdate, uint256 maxAgeAllowed);

    // ---------- Modifiers ----------

    modifier onlyUpdater() {
        if (msg.sender != updater) revert NotAuthorized();
        _;
    }

    constructor(uint256 initialRate) {
        if (initialRate == 0) revert RateCannotBeZero();

        updater = msg.sender;
        maxDeviationBps = 500;
        maxAge = 4 days;
        rate = initialRate;
        updatedAt = block.timestamp;

        emit RateUpdated(0, initialRate, block.timestamp);
    }

    function updateRate(uint256 newRate) public onlyUpdater {
        uint256 oldRate = rate;
        uint256 diff = newRate > oldRate ? newRate - oldRate : oldRate - newRate;

        if (diff * 10000 > oldRate * maxDeviationBps) revert DeviationTooHigh(oldRate, newRate);

        rate = newRate;
        updatedAt = block.timestamp;

        emit RateUpdated(oldRate, newRate, block.timestamp);
    }

    function latestRate() public view returns (uint256) {
        // O prazo é de dias; uma manipulação de segundos pelos validadores é irrelevante.
        // forge-lint: disable-next-line(block-timestamp)
        if (block.timestamp > updatedAt + maxAge) revert StaleRate(updatedAt, maxAge);
        return rate;
    }
}