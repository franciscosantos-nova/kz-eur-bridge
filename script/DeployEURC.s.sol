// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {EurAoaOracle} from "../src/EurAoaOracle.sol";
import {EuroVault} from "../src/EuroVault.sol";

contract DeployEURC is Script {
    // EURC oficial da Circle na Base Sepolia
    address constant EURC = 0x808456652fdb597867f38412077A9182bf77359F;
    uint256 constant INITIAL_RATE = 106550000000; // 1065,50 AOA/EUR

    function run() external {
        uint256 liquidity = IERC20(EURC).balanceOf(msg.sender);
        require(liquidity > 0, "Sem EURC: usa o faucet primeiro");

        vm.startBroadcast();

        EurAoaOracle oracle = new EurAoaOracle(INITIAL_RATE);
        EuroVault vault = new EuroVault(address(oracle), EURC);

        IERC20(EURC).approve(address(vault), liquidity);
        vault.depositLiquidity(liquidity);

        vm.stopBroadcast();

        console.log("EURC (Circle):", EURC);
        console.log("EurAoaOracle: ", address(oracle));
        console.log("EuroVault:    ", address(vault));
        console.log("Liquidez:     ", liquidity);
    }
}
