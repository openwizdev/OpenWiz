# Recorded dependency set, version 1

The approved direct dependencies are `serde` (with `derive`) and `serde_json`.
The visual terminal crate alone may directly depend on `ratatui` and `crossterm`;
`openwiz-tests` reaches the terminal as a dev-dependency. Neither visual library
may be reachable through normal dependencies from the agent CLI or backend.

These registry name/version/licence/checksum facts are an independent approval
record, not generated from the lockfile during a test. The tests compare every
locked external crate with this record and check dependency direction using
Cargo metadata. Changing an approved dependency still needs the owner's approval.
Every row uses `registry+https://github.com/rust-lang/crates.io-index`.
The first table covers the base libraries; the second covers the visual pair
and its transitives, including platform-specific and build dependencies.

| Crate | Version | Licence | Kind | Required by | Checksum (`Cargo.lock`) |
| --- | --- | --- | --- | --- | --- |
| `itoa` | `1.0.18` | MIT OR Apache-2.0 | transitive | `serde_json` | `8f42a60cbdf9a97f5d2305f08a87dc4e09308d1276d28c869c684d7777685682` |
| `memchr` | `2.8.3` | Unlicense OR MIT | transitive | `serde_json` | `cf8baf1c55e62ffcace7a9f06f4bd9cd3f0c4beb022d3b367256b91b87513d98` |
| `proc-macro2` | `1.0.107` | MIT OR Apache-2.0 | transitive | `quote`, `serde_derive`, `syn` | `985e7ec9bb745e6ce6535b544d84d6cd6f7ad8bd711c398938ae983b91a766d9` |
| `quote` | `1.0.47` | MIT OR Apache-2.0 | transitive | `serde_derive`, `syn` | `1fbf4db142a473a8d80c26bbf18454ed458bf8d26c8219c331daecfdbd079001` |
| `serde` | `1.0.229` | MIT OR Apache-2.0 | direct | `openwiz-core`, `openwiz-adapter-cloudroom`, `openwiz-cli`, `serde_json` | `4148590afebada386688f18773da617792bf2ef03ffc1e4cbd2b1d45b023e0ba` |
| `serde_core` | `1.0.229` | MIT OR Apache-2.0 | transitive | `serde`, `serde_json` | `67dca2c9c51e58a4791a4b1ed58308b39c64224d349a935ab5039aa360942a48` |
| `serde_derive` | `1.0.229` | MIT OR Apache-2.0 | transitive | `serde`, `serde_core` | `e7a5d71263a5a7d47b41f6b3f06ba276f10cc18b0931f1799f710578e2309348` |
| `serde_json` | `1.0.154` | MIT OR Apache-2.0 | direct | `openwiz-adapter-cloudroom`, `openwiz-cli`, `openwiz-tests` | `e7e9cc8b1b85264074fbcc02a88680c4096b1e47df8f739dceb03bf482f04bd6` |
| `syn` | `3.0.9` | MIT OR Apache-2.0 | transitive | `serde_derive` | `d78c8dee4c7bf0e14673097256fed6142ce9d3b85a408189d07482442145823b` |
| `unicode-ident` | `1.0.27` | (MIT OR Apache-2.0) AND Unicode-3.0 | transitive | `proc-macro2`, `syn` | `a2c754d6c33795a1c324727428e5a7dedb5b06195f9890bdbcba760d3e246563` |
| `zmij` | `1.0.23` | MIT | transitive | `serde_json` | `29666d0abbfad1e3dc4dcf6144730dd3a3ab225bbbdac83319345b1b44ccfc1b` |

## Visual terminal dependencies

| Crate | Version | Licence | Kind | Required by | Checksum (`Cargo.lock`) |
| --- | --- | --- | --- | --- | --- |
| `allocator-api2` | `0.2.21` | MIT OR Apache-2.0 | transitive (visual only) | `hashbrown` | `683d7910e743518b0e34f1186f92494becacb047c7b6bf616c96772180fef923` |
| `approx` | `0.5.1` | Apache-2.0 | transitive (visual only) | `palette` | `cab112f0a86d568ea0e627cc1d6be74a1e9cd55214684db5561995f6dad897c6` |
| `autocfg` | `1.5.1` | Apache-2.0 OR MIT | transitive (visual only) | `num-traits` | `f2032f911046de80f0a198e0901378627c33f59ea0ac00e363d481118bd70a53` |
| `bitflags` | `2.13.2` | MIT OR Apache-2.0 | transitive (visual only) | `crossterm`, `line-clipping`, `ratatui-core`, `ratatui-widgets`, `redox_syscall`, `rustix` | `3ded4057c258ba199e2d26386d3af3780957ecaee6c4ef4041c6b4b8b97c0b06` |
| `by_address` | `1.2.1` | MIT OR Apache-2.0 | transitive (visual only) | `palette_derive` | `64fa3c856b712db6612c019f14756e64e4bcea13337a6b33b696333a9eaa2d06` |
| `castaway` | `0.2.4` | MIT | transitive (visual only) | `compact_str` | `dec551ab6e7578819132c713a93c022a05d60159dc86e7a7050223577484c55a` |
| `cfg-if` | `1.0.5` | MIT OR Apache-2.0 | transitive (visual only) | `compact_str`, `parking_lot_core`, `ratatui-crossterm` | `4e7648175b45a9a48536d676f68d918270699102aa8dab5496df06904c914600` |
| `compact_str` | `0.9.1` | MIT | transitive (visual only) | `ratatui-core` | `9dfdd1c2274d9aa354115b09dc9a901d6c5576818cdf70d14cae2bdb47df00ab` |
| `convert_case` | `0.10.0` | MIT | transitive (visual only) | `derive_more-impl` | `633458d4ef8c78b72454de2d54fd6ab2e60f9e02be22f3c6104cdc8a4e0fceb9` |
| `crossterm` | `0.29.0` | MIT | direct (visual only) | `openwiz-terminal`, `ratatui-crossterm` | `d8b9f2e4c67f833b660cdb0a3523065869fb35570177239812ed4c905aeff87b` |
| `crossterm_winapi` | `0.9.1` | MIT | transitive (visual only) | `crossterm` | `acdd7c62a3665c7f6830a51635d9ac9b23ed385797f70a83bb8bafe9c572ab2b` |
| `darling` | `0.24.1` | MIT | transitive (visual only) | `instability` | `ed17f5901b6630b993ca003def43f2f8ef4014fc13b047b57aad617ff32bc2ec` |
| `darling_core` | `0.24.1` | MIT | transitive (visual only) | `darling`, `darling_macro` | `6837e2cf7485aaae18f86181d2f0e9a7ed297a025e220aeabf63fdebd3a2ddff` |
| `darling_macro` | `0.24.1` | MIT | transitive (visual only) | `darling` | `2ac7135c3ef02b2f7833bbeb1be5ba7f966dcde8a87c6b87f65a778d71a02785` |
| `deranged` | `0.5.9` | MIT OR Apache-2.0 | transitive (visual only) | `time` | `9e9de72ce2ad1f90dc62fa25f0f430ef85eb4b0d8fa0be4f30373bc40a21d28e` |
| `derive_more` | `2.1.1` | MIT | transitive (visual only) | `crossterm` | `d751e9e49156b02b44f9c1815bcb94b984cdcc4396ecc32521c739452808b134` |
| `derive_more-impl` | `2.1.1` | MIT | transitive (visual only) | `derive_more` | `799a97264921d8623a957f6c3b9011f3b5492f557bbb7a5a19b7fa6d06ba8dcb` |
| `document-features` | `0.2.12` | MIT OR Apache-2.0 | transitive (visual only) | `crossterm` | `d4b8a88685455ed29a21542a33abd9cb6510b6b129abadabdcef0f4c55bc8f61` |
| `either` | `1.19.0` | MIT OR Apache-2.0 | transitive (visual only) | `itertools` | `0e9c71c2167ca323c882b99918929403426e2373ea17242ff5653e0d5e1058be` |
| `equivalent` | `1.0.3` | Apache-2.0 OR MIT | transitive (visual only) | `hashbrown` | `00d174d5400e5e8fd687ad1049e2f578285fa914201b1af7e8b112a4546bd826` |
| `errno` | `0.3.14` | MIT OR Apache-2.0 | transitive (visual only) | `rustix`, `signal-hook-registry` | `39cab71617ae0d63f51a36d69f866391735b51691dbda63cf6f96d042b63efeb` |
| `foldhash` | `0.2.0` | Zlib | transitive (visual only) | `hashbrown` | `77ce24cb58228fbb8aa041425bb1050850ac19177686ea6e0f41a70416f56fdb` |
| `hashbrown` | `0.17.1` | MIT OR Apache-2.0 | transitive (visual only) | `kasuari`, `lru`, `ratatui-core`, `ratatui-widgets` | `ed5909b6e89a2db4456e54cd5f673791d7eca6732202bbf2a9cc504fe2f9b84a` |
| `heck` | `0.5.0` | MIT OR Apache-2.0 | transitive (visual only) | `strum_macros` | `2304e00983f87ffb38b55b444b5e3b60a884b5d30c0fca7d82fe33449bbe55ea` |
| `ident_case` | `1.0.1` | MIT/Apache-2.0 | transitive (visual only) | `darling_core` | `b9e0384b61958566e926dc50660321d12159025e767c18e043daf26b70104c39` |
| `indoc` | `2.0.8` | MIT OR Apache-2.0 | transitive (visual only) | `instability`, `ratatui-widgets` | `a37b2691796cffeb8a8cd305ac66e65841559f147f4e63231d0eafa4db5384d1` |
| `instability` | `0.3.14` | MIT | transitive (visual only) | `ratatui`, `ratatui-crossterm`, `ratatui-widgets` | `4c3b5acc1e2fd9375041a388da33d1eb8aed5f7a8c0dd3543e3ea2805adfbe20` |
| `itertools` | `0.14.0` | MIT OR Apache-2.0 | transitive (visual only) | `ratatui-core`, `ratatui-widgets`, `unicode-truncate` | `2b192c782037fadd9cfa75548310488aabdbf3d2da73885b31bd0abd03351285` |
| `kasuari` | `0.4.13` | MIT OR Apache-2.0 | transitive (visual only) | `ratatui-core` | `72f14c90e40a6133f4805b83542a7ed7364f56070b447f56e7f4e90297122209` |
| `libc` | `0.2.191` | MIT OR Apache-2.0 | transitive (visual only) | `errno`, `mio`, `num_threads`, `parking_lot_core`, `rustix`, `signal-hook`, `signal-hook-mio`, `signal-hook-registry`, `time` | `65cd87c9a6d60536580b316ad985726104730a5151c99845f2490428ef91240a` |
| `libm` | `0.2.16` | MIT | transitive (visual only) | `palette`, `palette_math` | `b6d2cec3eae94f9f509c767b45932f1ada8350c4bdb85af2fcab4a3c14807981` |
| `line-clipping` | `0.3.8` | MIT OR Apache-2.0 | transitive (visual only) | `ratatui-widgets` | `e752191d037c44ad111a8caa762921926658402f01cc1253f7bef2020ece4f5e` |
| `linux-raw-sys` | `0.12.1` | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | transitive (visual only) | `rustix` | `32a66949e030da00e8c7d4434b251670a91556f4144941d37452769c25d58a53` |
| `litrs` | `1.0.1` | MIT OR Apache-2.0 | transitive (visual only) | `document-features` | `4744e383959f0db86ede514b809b1c53251889093803c05267acc7d4e7030d70` |
| `lock_api` | `0.4.14` | MIT OR Apache-2.0 | transitive (visual only) | `parking_lot` | `224399e74b87b5f3557511d98dff8b14089b3dadafcab6bb93eab67d3aace965` |
| `log` | `0.4.35` | MIT OR Apache-2.0 | transitive (visual only) | `mio` | `5d15f86d12da44cd8d4ec3c73984537eb7f4cadcb9776a575a0a8a05ca11005c` |
| `lru` | `0.18.5` | MIT | transitive (visual only) | `ratatui-core` | `ef9ac18847474e638e3702b76c65d4eb93428471a74778ef0f1be711717f89b5` |
| `mio` | `1.2.4` | MIT | transitive (visual only) | `crossterm`, `signal-hook-mio` | `1788edb87fdc09c7e26304471e2f5be8cdefb1b6930d6e3985fc02ff53bf86ee` |
| `num-conv` | `0.2.2` | MIT OR Apache-2.0 | transitive (visual only) | `time` | `521739c6d2bac4aa25192232afe6841231376b2b26d4d9fae5ecf8ca5772e441` |
| `num-traits` | `0.2.19` | MIT OR Apache-2.0 | transitive (visual only) | `approx` | `071dfc062690e90b734c0b2273ce72ad0ffa95f0c74596bc250dcfd960262841` |
| `num_threads` | `0.1.8` | MIT OR Apache-2.0 | transitive (visual only) | `time` | `cabcc654086861f9e1bc5115258de62ef92c79b20f4615a1b0cc57c4e82027d4` |
| `palette` | `0.7.7` | MIT OR Apache-2.0 | transitive (visual only) | `ratatui-core` | `ddeed8580d347d2abf3dcf06a5f0b3dc020258338526b277847cd4248a70fc64` |
| `palette_derive` | `0.7.7` | MIT OR Apache-2.0 | transitive (visual only) | `palette` | `88537020289b719d81be994ccf1bbf4990f477e2f69ee52fe3e45f43a02e56be` |
| `palette_math` | `0.7.7` | MIT OR Apache-2.0 | transitive (visual only) | `palette` | `6e6eb142958d64335fb0e345c5b9ead2ecd6fc438c307e9d7d3c4fd428dbaf12` |
| `parking_lot` | `0.12.5` | MIT OR Apache-2.0 | transitive (visual only) | `crossterm` | `93857453250e3077bd71ff98b6a65ea6621a19bb0f559a85248955ac12c45a1a` |
| `parking_lot_core` | `0.9.12` | MIT OR Apache-2.0 | transitive (visual only) | `parking_lot` | `2621685985a2ebf1c516881c026032ac7deafcda1a2c9b7850dc81e3dfcb64c1` |
| `portable-atomic` | `1.15.0` | Apache-2.0 OR MIT | transitive (visual only) | `kasuari` | `05c8b63e8d9609db387f0324918f81d68fe27748f084ef092fb35954d0539a85` |
| `powerfmt` | `0.2.1` | MIT OR Apache-2.0 | transitive (visual only) | `time` | `4a6394b9e965e73d0a289ee54f589087e2c676aedf60885baf52c76b771e4958` |
| `ratatui` | `0.30.2` | MIT | direct (visual only) | `openwiz-terminal` | `3274ba0a2c5e1bcad2a2005d20f4dc59dad26b2eb0940fb094500dba4099d57d` |
| `ratatui-core` | `0.1.2` | MIT | transitive (visual only) | `ratatui`, `ratatui-crossterm`, `ratatui-widgets` | `cbb175c433c8e28a809d1f5773a2ae96e68c0ce40db865cbab1020bf33ae479c` |
| `ratatui-crossterm` | `0.1.2` | MIT | transitive (visual only) | `ratatui` | `567584a3b0e6a8203c23de40b4861497266725eb5363dbfd18a1edd603cca9f0` |
| `ratatui-widgets` | `0.3.2` | MIT | transitive (visual only) | `ratatui` | `66e3d19bcc9130ca376277d93b60767ff121ace3be06f5f95f81dd68956407d1` |
| `redox_syscall` | `0.5.18` | MIT | transitive (visual only) | `parking_lot_core` | `ed2bf2547551a7053d6fdfafda3f938979645c44812fbfcda098faae3f1a362d` |
| `rustc_version` | `0.4.1` | MIT OR Apache-2.0 | transitive (visual only) | `derive_more-impl` | `cfcb3a22ef46e85b45de6ee7e79d063319ebb6594faafcf1c225ea92ab6e9b92` |
| `rustix` | `1.1.6` | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | transitive (visual only) | `crossterm` | `e5e76742e5294153d4dde1207dbec5bdd81eef6fabdc0d2118babadabfd858aa` |
| `rustversion` | `1.0.23` | MIT OR Apache-2.0 | transitive (visual only) | `castaway`, `compact_str`, `indoc` | `cf54715a573b99ac80df0bc206da022bcd442c974952c7b9720069370852e21f` |
| `ryu` | `1.0.23` | Apache-2.0 OR BSL-1.0 | transitive (visual only) | `compact_str` | `9774ba4a74de5f7b1c1451ed6cd5285a32eddb5cccb8cc655a4e50009e06477f` |
| `scopeguard` | `1.2.0` | MIT OR Apache-2.0 | transitive (visual only) | `lock_api` | `94143f37725109f92c262ed2cf5e59bce7498c01bcc1502d7b9afe439a4e9f49` |
| `semver` | `1.0.28` | MIT OR Apache-2.0 | transitive (visual only) | `rustc_version` | `8a7852d02fc848982e0c167ef163aaff9cd91dc640ba85e263cb1ce46fae51cd` |
| `signal-hook` | `0.3.18` | Apache-2.0/MIT | transitive (visual only) | `crossterm`, `signal-hook-mio` | `d881a16cf4426aa584979d30bd82cb33429027e42122b169753d6ef1085ed6e2` |
| `signal-hook-mio` | `0.2.5` | MIT OR Apache-2.0 | transitive (visual only) | `crossterm` | `b75a19a7a740b25bc7944bdee6172368f988763b744e3d4dfe753f6b4ece40cc` |
| `signal-hook-registry` | `1.4.8` | MIT OR Apache-2.0 | transitive (visual only) | `signal-hook` | `c4db69cba1110affc0e9f7bcd48bbf87b3f4fc7c61fc9155afd4c469eb3d6c1b` |
| `smallvec` | `1.16.4` | MIT OR Apache-2.0 | transitive (visual only) | `parking_lot_core` | `d0d5d4b1981b8bbbb7aed204cae5726d683d5d6ac7e74ec54122ea28f315e7c8` |
| `static_assertions` | `1.1.0` | MIT OR Apache-2.0 | transitive (visual only) | `compact_str` | `a2eb9349b6444b326872e140eb1cf5e7c522154d69e7a0ffb0fb81c06b37543f` |
| `strsim` | `0.11.1` | MIT | transitive (visual only) | `darling_core` | `7da8b5736845d9f2fcb837ea5d9e2628564b3b043a70948a3f0b778838c5fb4f` |
| `strum` | `0.28.0` | MIT | transitive (visual only) | `ratatui-core`, `ratatui-widgets` | `9628de9b8791db39ceda2b119bbe13134770b56c138ec1d3af810d045c04f9bd` |
| `strum_macros` | `0.28.0` | MIT | transitive (visual only) | `strum` | `ab85eea0270ee17587ed4156089e10b9e6880ee688791d45a905f5b1ca36f664` |
| `syn` | `2.0.119` | MIT OR Apache-2.0 | transitive (visual only) | `derive_more-impl`, `palette_derive`, `strum_macros` | `872831b642d1a07999a962a351ed35b955ea2cfc8f3862091e2a240a84f17297` |
| `thiserror` | `2.0.21` | MIT OR Apache-2.0 | transitive (visual only) | `kasuari`, `ratatui-core` | `09e52cb86a36cede5cb101bf8908837b3e4c6e5e59fe7fd85c23fb56200d189e` |
| `thiserror-impl` | `2.0.21` | MIT OR Apache-2.0 | transitive (visual only) | `thiserror` | `fe5197923287db20a58125f0bc85c062f7f2c892de97b18c356f9efb14b28524` |
| `time` | `0.3.55` | MIT OR Apache-2.0 | transitive (visual only) | `ratatui-widgets` | `cdb87b95ec50ddfa440816d227a17b2ccbdda963a316a727fda0fc4334f7d134` |
| `time-core` | `0.1.9` | MIT OR Apache-2.0 | transitive (visual only) | `time` | `9e1c906769ad99c88eaa54e728060edef082f8e358ff32030cb7c7d315e81109` |
| `unicode-segmentation` | `1.13.3` | MIT OR Apache-2.0 | transitive (visual only) | `convert_case`, `ratatui-core`, `ratatui-widgets`, `unicode-truncate` | `c6f5d3c3b1bf09027a88a6bc961fc00497d651009560b5463668dc81b0fa87a8` |
| `unicode-truncate` | `2.0.1` | MIT OR Apache-2.0 | transitive (visual only) | `ratatui-core` | `16b380a1238663e5f8a691f9039c73e1cdae598a30e9855f541d29b08b53e9a5` |
| `unicode-width` | `0.2.3` | MIT OR Apache-2.0 | transitive (visual only) | `ratatui-core`, `ratatui-widgets`, `unicode-truncate` | `ca718471876992059f251e33aafc334346ada08042b7661dd1fe313a9bced557` |
| `wasi` | `0.11.1+wasi-snapshot-preview1` | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | transitive (visual only) | `mio` | `ccf3ec651a847eb01de73ccad15eb7d99f80485de043efb2f370cd654f4ea44b` |
| `winapi` | `0.3.9` | MIT/Apache-2.0 | transitive (visual only) | `crossterm`, `crossterm_winapi` | `5c839a674fcd7a98952e593242ea400abe93992746761e38641405d28b00f419` |
| `winapi-i686-pc-windows-gnu` | `0.4.0` | MIT/Apache-2.0 | transitive (visual only) | `winapi` | `ac3b87c63620426dd9b991e5ce0329eff545bccbbb34f3be09ff6fb6ab51b7b6` |
| `winapi-x86_64-pc-windows-gnu` | `0.4.0` | MIT/Apache-2.0 | transitive (visual only) | `winapi` | `712e227841d057c1ee1cd2fb22fa7e5a5461ae8e48fa2ca79ec42cfc1931183f` |
| `windows-link` | `0.2.1` | MIT OR Apache-2.0 | transitive (visual only) | `parking_lot_core`, `windows-sys` | `f0805222e57f7521d6a62e36fa9163bc891acd422f971defe97d64e70d0a4fe5` |
| `windows-sys` | `0.61.2` | MIT OR Apache-2.0 | transitive (visual only) | `errno`, `mio`, `rustix` | `ae137229bcbd6cdf0f7b80a31df61766145077ddf49416a728b02cb3921ff3fc` |
