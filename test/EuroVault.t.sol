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
    uint256 constant SON = 2;
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
        uint256 aoa = 1000000000; // 10 milhões de kz
        (,, uint256 net) = vault.quote(aoa);

        vm.expectRevert(abi.encodeWithSelector(EuroVault.InsufficientLiquidity.selector, LIQUIDITY, net));
        vault.creditFromKwanza(USER, aoa, 0, "MCX-BIG");
    }

    function test_RevertWhen_PayoutExceedsBalance() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        vm.expectRevert(abi.encodeWithSelector(EuroVault.InsufficientBalance.selector, NET_50K, 100e6));
        vault.payout(USER, 100e6, restaurant, "PAY-0001");
    }

    function test_RevertWhen_AttackerCredits() public {
        vm.prank(attacker);
        vm.expectRevert(EuroVault.NotAuthorized.selector);
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
    }

    function test_RevertWhen_OracleIsStale() public {
        uint256 lastUpdate = oracle.updatedAt();
        vm.warp(block.timestamp + 4 days + 1);

        vm.expectRevert(abi.encodeWithSelector(EurAoaOracle.StaleRate.selector, lastUpdate, 4 days));
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
        (,, uint256 quoted) = vault.quote(AOA_50K);

        oracle.updateRate(RATE * 103 / 100);
        (,, uint256 netAfter) = vault.quote(AOA_50K);

        vm.expectRevert(abi.encodeWithSelector(EuroVault.Slippage.selector, netAfter, quoted));
        vault.creditFromKwanza(USER, AOA_50K, quoted, "MCX-0001");
    }

    function test_CreditWhenRateMovesInUserFavour() public {
        (,, uint256 quoted) = vault.quote(AOA_50K);

        oracle.updateRate(RATE * 97 / 100);

        vault.creditFromKwanza(USER, AOA_50K, quoted, "MCX-0001");
        assertGt(vault.balanceOf(USER), quoted);
    }

    // ---------- Margem ----------

    function test_SetSpreadChangesWhatUserReceives() public {
        vault.setSpread(0);
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        assertEq(vault.balanceOf(USER), NET_50K + FEE_50K);
        assertEq(vault.totalFeesCollected(), 0);
    }

    function test_RevertWhen_SpreadTooHigh() public {
        vm.expectRevert(abi.encodeWithSelector(EuroVault.SpreadTooHigh.selector, 501));
        vault.setSpread(501);
    }

    function test_RevertWhen_AttackerSetsSpread() public {
        vm.prank(attacker);
        vm.expectRevert(EuroVault.NotAuthorized.selector);
        vault.setSpread(500);
    }

    // ---------- Referências únicas ----------

    function test_RevertWhen_CreditRefReused() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        vm.expectRevert(abi.encodeWithSelector(EuroVault.RefAlreadyProcessed.selector, bytes32("MCX-0001")));
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        assertEq(vault.balanceOf(USER), NET_50K);
    }

    function test_RevertWhen_PayoutRefReused() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
        vault.payout(USER, 10e6, restaurant, "PAY-0001");

        vm.expectRevert(abi.encodeWithSelector(EuroVault.RefAlreadyProcessed.selector, bytes32("PAY-0001")));
        vault.payout(USER, 10e6, restaurant, "PAY-0001");

        assertEq(eurc.balanceOf(restaurant), 10e6);
    }

    function test_RevertWhen_RefIsEmpty() public {
        vm.expectRevert(EuroVault.InvalidRef.selector);
        vault.creditFromKwanza(USER, AOA_50K, 0, bytes32(0));
    }

    function test_RevertedCreditDoesNotBurnRef() public {
        uint256 lastUpdate = oracle.updatedAt();
        vm.warp(block.timestamp + 4 days + 1);

        vm.expectRevert(abi.encodeWithSelector(EurAoaOracle.StaleRate.selector, lastUpdate, 4 days));
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

        vm.expectRevert(abi.encodeWithSelector(EuroVault.InsufficientLiquidity.selector, available, available + 1));
        vault.withdrawLiquidity(treasury, available + 1);
    }

    function test_RevertWhen_AttackerWithdraws() public {
        vm.prank(attacker);
        vm.expectRevert(EuroVault.NotAuthorized.selector);
        vault.withdrawLiquidity(attacker, 1);
    }

    // ---------- Transferências entre clientes ----------

    function test_TransferBetweenUsers() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
        uint256 vaultEurcBefore = eurc.balanceOf(address(vault));

        vault.transferBetweenUsers(USER, SON, 20e6, "P2P-0001");

        assertEq(vault.balanceOf(USER), NET_50K - 20e6);
        assertEq(vault.balanceOf(SON), 20e6);
        assertEq(vault.totalLiabilities(), NET_50K);
        assertEq(eurc.balanceOf(address(vault)), vaultEurcBefore);
    }

    function test_RevertWhen_TransferExceedsBalance() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        vm.expectRevert(abi.encodeWithSelector(EuroVault.InsufficientBalance.selector, NET_50K, 100e6));
        vault.transferBetweenUsers(USER, SON, 100e6, "P2P-0001");
    }

    function test_RevertWhen_TransferToSelf() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        vm.expectRevert(EuroVault.SameUser.selector);
        vault.transferBetweenUsers(USER, USER, 10e6, "P2P-0001");
    }

    // ---------- Eventos ----------

    function test_EmitsKwanzaCredited() public {
        vm.expectEmit(address(vault));
        emit EuroVault.KwanzaCredited(USER, bytes32("MCX-0001"), AOA_50K, NET_50K + FEE_50K, FEE_50K, NET_50K);

        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
    }

    function test_EmitsPayout() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        vm.expectEmit(address(vault));
        emit EuroVault.Payout(USER, bytes32("PAY-0001"), restaurant, 20e6);

        vault.payout(USER, 20e6, restaurant, "PAY-0001");
    }

    function test_EmitsInternalTransfer() public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");

        vm.expectEmit(address(vault));
        emit EuroVault.InternalTransfer(USER, SON, bytes32("P2P-0001"), 20e6);

        vault.transferBetweenUsers(USER, SON, 20e6, "P2P-0001");
    }

    function test_EmitsSpreadUpdated() public {
        vm.expectEmit(address(vault));
        emit EuroVault.SpreadUpdated(100, 200);

        vault.setSpread(200);
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

    function testFuzz_TransferPreservesTotal(uint256 amount) public {
        vault.creditFromKwanza(USER, AOA_50K, 0, "MCX-0001");
        amount = bound(amount, 0, NET_50K);

        vault.transferBetweenUsers(USER, SON, amount, "P2P-FUZZ");

        assertEq(vault.balanceOf(USER) + vault.balanceOf(SON), NET_50K);
        assertEq(vault.totalLiabilities(), NET_50K);
    }
}
