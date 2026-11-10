// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {EurAoaOracle} from "../src/EurAoaOracle.sol";
import {EuroVault} from "../src/EuroVault.sol";
import {MockEURC} from "../src/MockEURC.sol";

contract EuroVaultTest is Test {
    EurAoaOracle oracle;
    MockEURC eurc;
    EuroVault vault;

    address restaurant = makeAddr("restaurant");
    address attacker = makeAddr("attacker");

    uint256 constant RATE = 106550000000;   // 1065,50 AOA/EUR
    uint256 constant LIQUIDITY = 500e6;     // 500 €
    uint256 constant USER = 1;
    uint256 constant AOA_50K = 5000000;     // 50.000,00 kz
    uint256 constant EUR_50K = 46926325;    // 46,926325 €

    function setUp() public {
        oracle = new EurAoaOracle(RATE);
        eurc = new MockEURC();
        vault = new EuroVault(address(oracle), address(eurc));

        eurc.mint(address(this), 1000e6);
        eurc.approve(address(vault), LIQUIDITY);
        vault.depositLiquidity(LIQUIDITY);
    }

    function test_CreditFromKwanza() public {
        vault.creditFromKwanza(USER, AOA_50K);

        assertEq(vault.balanceOf(USER), EUR_50K);
        assertEq(vault.totalLiabilities(), EUR_50K);
        assertEq(vault.availableLiquidity(), LIQUIDITY - EUR_50K);
    }

    function test_PayoutToRestaurant() public {
        vault.creditFromKwanza(USER, AOA_50K);
        vault.payout(USER, 20e6, restaurant);

        assertEq(eurc.balanceOf(restaurant), 20e6);
        assertEq(vault.balanceOf(USER), EUR_50K - 20e6);
        assertEq(vault.totalLiabilities(), EUR_50K - 20e6);
    }

    function test_RevertWhen_InsufficientLiquidity() public {
        vm.expectRevert("Insufficient liquidity");
        vault.creditFromKwanza(USER, 1000000000);
    }

    function test_RevertWhen_PayoutExceedsBalance() public {
        vault.creditFromKwanza(USER, AOA_50K);
        vm.expectRevert("Insufficient balance");
        vault.payout(USER, 100e6, restaurant);
    }

    function test_RevertWhen_AttackerCredits() public {
        vm.prank(attacker);
        vm.expectRevert("Not authorized");
        vault.creditFromKwanza(USER, AOA_50K);
    }

    function test_RevertWhen_OracleIsStale() public {
        vm.warp(block.timestamp + 4 days + 1);
        vm.expectRevert("Stale rate");
        vault.creditFromKwanza(USER, AOA_50K);
    }
    function testFuzz_CreditKeepsVaultSolvent(uint256 aoaCents) public {
    aoaCents = bound(aoaCents, 1, 50_000_000);

    vault.creditFromKwanza(USER, aoaCents);

    // ativos >= passivos
    assertGe(eurc.balanceOf(address(vault)), vault.totalLiabilities());
}
    function testFuzz_CreditThenPayout(uint256 aoaCents, uint256 spend) public {
    aoaCents = bound(aoaCents, 1, 50_000_000);
    vault.creditFromKwanza(USER, aoaCents);

    uint256 balanceBefore = vault.balanceOf(USER);
    spend = bound(spend, 0, balanceBefore);                          // TODO 1

    vault.payout(USER, spend, restaurant);                           // TODO 2

    assertGe(eurc.balanceOf(address(vault)), vault.totalLiabilities()); // TODO 3: solvente
    assertEq(eurc.balanceOf(restaurant), spend);                        // TODO 3: restaurante
    assertEq(vault.balanceOf(USER), balanceBefore - spend);             // TODO 3: cliente
}
}