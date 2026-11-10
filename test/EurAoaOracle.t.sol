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

    function test_RevertWhen_AttackerUpdates() public {
        vm.prank(attacker);
        vm.expectRevert("Not authorized");
        oracle.updateRate(1);
    }

    function test_RevertWhen_DeviationTooHigh() public {
        vm.expectRevert("Deviation too high");
        oracle.updateRate(RATE * 110 / 100);
    }

    function test_RevertWhen_RateIsStale() public {
        vm.warp(block.timestamp + 4 days + 1);
        vm.expectRevert("Stale rate");
        oracle.latestRate();
    }

    function test_RevertWhen_InitialRateIsZero() public {
        vm.expectRevert("Rate cannot be zero");
        new EurAoaOracle(0);
    }
    function test_UpdateDownwards() public {
    uint256 newRate = RATE * 97 / 100;   // kwanza valoriza 3%
    oracle.updateRate(newRate);
    assertEq(oracle.latestRate(), newRate);
}

    function test_RevertWhen_DropTooHigh() public {
    vm.expectRevert("Deviation too high");
    oracle.updateRate(RATE * 90 / 100);  // desce 10%
}
}