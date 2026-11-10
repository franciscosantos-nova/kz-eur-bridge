// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {EurAoaOracle} from "../src/EurAoaOracle.sol";
import {EuroVault} from "../src/EuroVault.sol";
import {MockEURC} from "../src/MockEURC.sol";

contract Deploy is Script {
    uint256 constant INITIAL_RATE = 106550000000; // 1065,50 AOA/EUR
    uint256 constant LIQUIDITY = 10_000e6;        // 10.000 EURC de teste

    function run() external {
        vm.startBroadcast();

        MockEURC eurc = new MockEURC();
        EurAoaOracle oracle = new EurAoaOracle(INITIAL_RATE);
        EuroVault vault = new EuroVault(address(oracle), address(eurc));

        eurc.mint(msg.sender, LIQUIDITY);
        eurc.approve(address(vault), LIQUIDITY);
        vault.depositLiquidity(LIQUIDITY);

        vm.stopBroadcast();

        console.log("MockEURC:     ", address(eurc));
        console.log("EurAoaOracle: ", address(oracle));
        console.log("EuroVault:    ", address(vault));
    }
}