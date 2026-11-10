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
    address treasury = makeAddr("treasury");

    uint256 constant RATE = 106550000000;
    uint256 constant LIQUIDITY = 500e6;
    uint256 constant USER = 1;
    uint256 constant AOA_50K = 5000000;
    uint256 constant NET_50K = 46457062;
    uint256 constant FEE_50K = 469263;

    function setUp() public {
        oracle = new EurAoaOracle(RATE);
        eurc = new MockEURC();
        vault = new EuroVault(address(oracle), address(eurc));

        eurc.mint(address(this), 1000e6);
        eurc.approve(address(vault), LIQUIDITY);
        vault.depositLiquidity(LIQUIDITY);
    }

    // ---------- Crédito e pagamento ----------

    function test_CreditFromKwanza() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        assertEq(vault.balanceOf(USER), NET_50K);
        assertEq(vault.totalLiabilities(), NET_50K);
        assertEq(vault.totalFeesCollected(), FEE_50K);
        assertEq(vault.availableLiquidity(), LIQUIDITY - NET_50K);
    }

    function test_PayoutToRestaurant() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
        vault.payout(USER, 20e6, restaurant, "PAY-0001");

        assertEq(eurc.balanceOf(restaurant), 20e6);
        assertEq(vault.balanceOf(USER), NET_50K - 20e6);
        assertEq(vault.totalLiabilities(), NET_50K - 20e6);
    }

    function test_RevertWhen_InsufficientLiquidity() public {
        vm.expectRevert("Insufficient liquidity");
        vault.creditFromKwanza(USER, 1000000000, 0, "MCX-BIG");
    }

    function test_RevertWhen_PayoutExceedsBalance() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
        vm.expectRevert("Insufficient balance");
        vault.payout(USER, 100e6, restaurant, "PAY-0001");
    }

    function test_RevertWhen_AttackerCredits() public {
        vm.prank(attacker);
        vm.expectRevert("Not authorized");
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
    }

    function test_RevertWhen_OracleIsStale() public {
        vm.warp(block.timestamp + 4 days + 1);
        vm.expectRevert("Stale rate");
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
    }

    // ---------- Cotação e slippage ----------

    function test_Quote() public view {
        (uint256 gross, uint256 fee, uint256 net) = vault.quote(AOA_50K);

        assertEq(gross, NET_50K + FEE_50K);
        assertEq(fee, FEE_50K);
        assertEq(net, NET_50K);
    }

    function test_CreditWithExactQuote() public {
        (,, uint256 quoted) = vault.quote(AOA_50K);
        vault.creditFromKwanza(USER, AOA_50K, quoted, "MCX-0001");

        assertEq(vault.balanceOf(USER), quoted);
    }

    function test_RevertWhen_RateMovesAgainstUser() public {
        (,, uint256 quoted) = vault.quote(AOA_50K);   // a app mostra este valor

        oracle.updateRate(RATE * 103 / 100);          // o kwanza perde 3% entretanto

        vm.expectRevert("Slippage");
        vault.creditFromKwanza(USER, AOA_50K, quoted, "MCX-0001");
    }

    function test_CreditWhenRateMovesInUserFavour() public {
        (,, uint256 quoted) = vault.quote(AOA_50K);

        oracle.updateRate(RATE * 97 / 100);           // o kwanza ganha 3%

        vault.creditFromKwanza(USER, AOA_50K, quoted, "MCX-0001");
        assertGt(vault.balanceOf(USER), quoted);      // recebeu mais do que lhe mostraram
    }

    // ---------- Margem ----------

    function test_SetSpreadChangesWhatUserReceives() public {
        vault.setSpread(0);
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        assertEq(vault.balanceOf(USER), NET_50K + FEE_50K);
        assertEq(vault.totalFeesCollected(), 0);
    }

    function test_RevertWhen_SpreadTooHigh() public {
        vm.expectRevert("Spread too high");
        vault.setSpread(501);
    }

    function test_RevertWhen_AttackerSetsSpread() public {
        vm.prank(attacker);
        vm.expectRevert("Not authorized");
        vault.setSpread(500);
    }

    // ---------- Referências únicas ----------

    function test_RevertWhen_CreditRefReused() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        vm.expectRevert("Ref already processed");
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        assertEq(vault.balanceOf(USER), NET_50K);
    }

    function test_RevertWhen_PayoutRefReused() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
        vault.payout(USER, 10e6, restaurant, "PAY-0001");

        vm.expectRevert("Ref already processed");
        vault.payout(USER, 10e6, restaurant, "PAY-0001");

        assertEq(eurc.balanceOf(restaurant), 10e6);
    }

    function test_RevertWhen_RefIsEmpty() public {
        vm.expectRevert("Invalid ref");
        vault.creditFromKwanza(USER, AOA_50K, 0, bytes32(0));
    }

    function test_RevertedCreditDoesNotBurnRef() public {
        vm.warp(block.timestamp + 4 days + 1);
        vm.expectRevert("Stale rate");
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        oracle.updateRate(RATE);
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
        assertEq(vault.balanceOf(USER), NET_50K);
    }

    // ---------- Retirar liquidez ----------

    function test_WithdrawProfits() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
        uint256 available = vault.availableLiquidity();

        vault.withdrawLiquidity(treasury, available);

        assertEq(eurc.balanceOf(treasury), available);
        assertEq(eurc.balanceOf(address(vault)), vault.totalLiabilities());
    }

    function test_RevertWhen_WithdrawTouchesCustomerFunds() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
        uint256 available = vault.availableLiquidity();

        vm.expectRevert("Insufficient liquidity");
        vault.withdrawLiquidity(treasury, available + 1);
    }

    function test_RevertWhen_AttackerWithdraws() public {
        vm.prank(attacker);
        vm.expectRevert("Not authorized");
        vault.withdrawLiquidity(attacker, 1);
    }

    // ---------- Fuzz ----------

    function testFuzz_CreditKeepsVaultSolvent(uint256 aoaCents) public {
        aoaCents = bound(aoaCents, 1, 50_000_000);
        vault.creditFromKwanza(USER, aoaCents, 0, "FUZZ-CREDIT");

        assertGe(eurc.balanceOf(address(vault)), vault.totalLiabilities());
    }

    function testFuzz_CreditThenPayout(uint256 aoaCents, uint256 spend) public {
        aoaCents = bound(aoaCents, 1, 50_000_000);
        vault.creditFromKwanza(USER, aoaCents, 0, "FUZZ-CREDIT");

        uint256 balanceBefore = vault.balanceOf(USER);
        spend = bound(spend, 0, balanceBefore);
        vault.payout(USER, spend, restaurant, "FUZZ-PAY");

        assertGe(eurc.balanceOf(address(vault)), vault.totalLiabilities());
        assertEq(eurc.balanceOf(restaurant), spend);
        assertEq(vault.balanceOf(USER), balanceBefore - spend);
    }

    function testFuzz_WithdrawNeverBreaksSolvency(uint256 aoaCents, uint256 amount) public {
        aoaCents = bound(aoaCents, 1, 50_000_000);
        vault.creditFromKwanza(USER, aoaCents, 0, "FUZZ-CREDIT");

        amount = bound(amount, 0, vault.availableLiquidity());
        vault.withdrawLiquidity(treasury, amount);

        assertGe(eurc.balanceOf(address(vault)), vault.totalLiabilities());
    }
}