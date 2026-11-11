// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {EurAoaOracle} from "../src/EurAoaOracle.sol";

contract EurAoaOracleTest is Test {
    EurAoaOracle oracle;
    address attacker = makeAddr("attacker");
    uint256 constant RATE = 106550000000;

    function setUp() public {
        oracle = new EurAoaOracle(RATE);
    }

    function test_InitialRate() public view {
        assertEq(oracle.latestRate(), RATE);
    }

    function test_UpdateWithinDeviation() public {
        uint256 newRate = RATE * 103 / 100;
        oracle.updateRate(newRate);
        assertEq(oracle.latestRate(), newRate);
    }

    function test_UpdateDownwards() public {
        uint256 newRate = RATE * 97 / 100;
        oracle.updateRate(newRate);
        assertEq(oracle.latestRate(), newRate);
    }

    function test_RevertWhen_AttackerUpdates() public {
        vm.prank(attacker);
        vm.expectRevert(EurAoaOracle.NotAuthorized.selector);
        oracle.updateRate(1);
    }

    function test_RevertWhen_DeviationTooHigh() public {
        uint256 newRate = RATE * 110 / 100;
        vm.expectRevert(abi.encodeWithSelector(EurAoaOracle.DeviationTooHigh.selector, RATE, newRate));
        oracle.updateRate(newRate);
    }

    function test_RevertWhen_DropTooHigh() public {
        uint256 newRate = RATE * 90 / 100;
        vm.expectRevert(abi.encodeWithSelector(EurAoaOracle.DeviationTooHigh.selector, RATE, newRate));
        oracle.updateRate(newRate);
    }

    function test_RevertWhen_RateIsStale() public {
        uint256 lastUpdate = oracle.updatedAt();
        vm.warp(block.timestamp + 4 days + 1);

        vm.expectRevert(abi.encodeWithSelector(EurAoaOracle.StaleRate.selector, lastUpdate, 4 days));
        oracle.latestRate();
    }

    function test_RevertWhen_InitialRateIsZero() public {
        vm.expectRevert(EurAoaOracle.RateCannotBeZero.selector);
        new EurAoaOracle(0);
    }

    function test_EmitsRateUpdated() public {
        uint256 newRate = RATE * 103 / 100;

        vm.expectEmit(address(oracle));
        emit EurAoaOracle.RateUpdated(RATE, newRate, block.timestamp);

        oracle.updateRate(newRate);
    }
}
