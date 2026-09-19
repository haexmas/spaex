# Changelog

## [5.1.1](https://github.com/haexmas/spaex/compare/v5.1.0...v5.1.1) (2026-09-19)


### Bug Fixes

* **release:** let manual dispatch target main via a version input ([1564488](https://github.com/haexmas/spaex/commit/1564488979b7c08e1a84aa42dc79319f0a99f5dd))

## [5.1.0](https://github.com/haexmas/spaex/compare/v5.0.0...v5.1.0) (2026-09-19)


### Features

* **composer:** deterministic fragment-to-batch partitioning ([9d3764a](https://github.com/haexmas/spaex/commit/9d3764acf0b2113617611e064328ea14cc617a9e))
* **composer:** dispatch batch calls concurrently ([398c6f3](https://github.com/haexmas/spaex/commit/398c6f398b832abe06276f45a4a6c61941b5a00f))
* **composer:** implement SPAEX_LLM_MODEL for the CLI-only path ([a64d28a](https://github.com/haexmas/spaex/commit/a64d28ac158ea22539a2622096c1634aa0dbcad8))
* **composer:** JSON-lines composer log, scaffold batching/reduce modules ([11bac0d](https://github.com/haexmas/spaex/commit/11bac0d0ee20648731ea0ff040f22ca9e8585b78))
* **composer:** log invocation progress and surface host load on timeout ([5e5c035](https://github.com/haexmas/spaex/commit/5e5c0354eb6cb9e456092f70cda07f08b419f221))
* **composer:** map-reduce composition (Spec 026 US1 MVP) ([a202b5f](https://github.com/haexmas/spaex/commit/a202b5f92540c403d53765bb79c958bc282dcf6b))
* **spec-027:** implement generic atom-category delivery and removal ([8396896](https://github.com/haexmas/spaex/commit/83968967ee5a017c89f030b424eccb3cdef645ba))


### Bug Fixes

* **behavior:** log the composed body when completeness check fails ([0632307](https://github.com/haexmas/spaex/commit/06323079ce1db97ba5461c91dcedb30c5d9ab6f5))
* **behavior:** require clause-shaped provenance citations ([90c63d8](https://github.com/haexmas/spaex/commit/90c63d8fa7c53659dec9a35fb9a69f903958290b))
* **behavior:** verify composer output completeness before publish ([65e9275](https://github.com/haexmas/spaex/commit/65e927597c66df5392a68086b5bcc6750661e12b))
* **composer:** align composition ceilings with spec ([c47ef34](https://github.com/haexmas/spaex/commit/c47ef34f0f2a4a9812561468ca4a01e87ddc0db4))
* **composer:** align merge ceiling documentation ([6357b34](https://github.com/haexmas/spaex/commit/6357b34abe08fbc2abe03beea33e409d6aea25ad))
* **composer:** decouple merge ceiling from batching ceiling ([9c6217d](https://github.com/haexmas/spaex/commit/9c6217dfb33f45a0377c03670ba7461351051cba))
* **composer:** don't reject a molecule for fragment count alone ([145a0eb](https://github.com/haexmas/spaex/commit/145a0ebfd87f4ab66d944a53b720c5a624d2b676))
* **composer:** enforce complete batch size limits ([7da874b](https://github.com/haexmas/spaex/commit/7da874bde3dfe79923055a891529f74ca362bb7b))
* **composer:** give merge steps their own byte ceiling ([e28eb66](https://github.com/haexmas/spaex/commit/e28eb66b240d13aacf1456a344c6ee6dd25a6c3d))
* **composer:** guard os.getloadavg for win32 typeshed stub ([40eb64b](https://github.com/haexmas/spaex/commit/40eb64bfd99bc721c09206fe2cb1ff11b3d0a289))
* **composer:** handle missing load average support ([6f39fbb](https://github.com/haexmas/spaex/commit/6f39fbb4d1de5fcdecfb88993024fb43b1343f64))
* **composer:** harden parallel dispatch diagnostics ([d2c9149](https://github.com/haexmas/spaex/commit/d2c9149353de585a9aacc21ea0cc0c3adba397c2))
* **composer:** increase default timeout to 300 seconds ([e414820](https://github.com/haexmas/spaex/commit/e4148200be90b2c6e7760d55a495f6f37934ebf9))
* **composer:** preserve batch clarification completeness context ([a56e69e](https://github.com/haexmas/spaex/commit/a56e69e46933f5ca4c3193fdabdb6e5da8f91ee3))
* **composer:** raise default Composer timeout to 900s ([d521ec3](https://github.com/haexmas/spaex/commit/d521ec3fbe493b8f455bf45e8b50feaff7d9cf66))
* **composer:** raise the default fragment-count batch guard from 12 to 200 ([2bcd80f](https://github.com/haexmas/spaex/commit/2bcd80ff10c6cdb8aac82c57bebba559eaad78a2))
* **composer:** tell the LLM every input fragment needs a citation ([e235556](https://github.com/haexmas/spaex/commit/e235556498daa794e0db344e0d85a3c3a54e8641))
* **composer:** tighten batch byte ceiling, fix dispatch cancellation bug ([7fe4a00](https://github.com/haexmas/spaex/commit/7fe4a00c12216bb969cd83458d04d61a5df8db1c))
* **composer:** treat merge ceiling as a sanity backstop, not tuning ([113a846](https://github.com/haexmas/spaex/commit/113a8465272a938c0c12d5366283ebfdb36e73fe))
* **composer:** verify batch completeness right after each batch call ([0b41fb8](https://github.com/haexmas/spaex/commit/0b41fb838a7c5eaaaedf6d12e5daf75707602602))
* **install:** preserve composer.log across generation rollback ([a5a955d](https://github.com/haexmas/spaex/commit/a5a955db71a142db1e37c9c56072da8a9e2864ed))
* **install:** preserve configured composer logs during rollback ([e200e62](https://github.com/haexmas/spaex/commit/e200e629ffaaba6392b6b948b32566b981da7134))
* **review:** address PR 144 findings ([676446f](https://github.com/haexmas/spaex/commit/676446fa8f31f5109d5e37a505007595aebd239a))
* **spec-027:** address CodeRabbit review findings ([3dd1dae](https://github.com/haexmas/spaex/commit/3dd1dae897114ea6f5d0087a6169310c07bcd0b5))
* **spec-027:** address CodeRabbit review findings on generic atom delivery ([2c0c3fb](https://github.com/haexmas/spaex/commit/2c0c3fb48e119bf19496e9af722adfd79ea9f52e))
* **tests:** update batch ceiling comment ([c842fc7](https://github.com/haexmas/spaex/commit/c842fc77feadd4ee162878d37ded6a8646110a72))


### Documentation

* **adr:** record independent merge ceiling ([e117ff6](https://github.com/haexmas/spaex/commit/e117ff60341c9bcd557f942fe1e07dce2e7d0902))
* **composer:** align invocation contract with cli-only mode ([3b61efa](https://github.com/haexmas/spaex/commit/3b61efac6f289914ca3807087153eb74ae44d50f))
* document first-time Nix flakes/direnv activation setup ([d5543f1](https://github.com/haexmas/spaex/commit/d5543f1a76af3889e5810fa497fb3d56d1eaf55e))
* record spec 026 and the composer scaling incident in the design record ([9ebe172](https://github.com/haexmas/spaex/commit/9ebe17249100b4bee54c67401d6f11e392588fe0))
* **spec-026:** address review findings ([e51e0df](https://github.com/haexmas/spaex/commit/e51e0df17323d882b14cc4c5756e42df892861ed))
* **spec-026:** confirm T020 against this project's real fragment set ([a6ebab5](https://github.com/haexmas/spaex/commit/a6ebab5a698c28ccecacd8e7dc002e96f1ec1279))
* **spec-026:** confirm T020 dogfood build after today's composer fixes ([1e471eb](https://github.com/haexmas/spaex/commit/1e471eba21e48a7a2effb028aaae9aedf5d497d1))
* **spec-026:** cross-reference contract and record ADR 0022 ([f92f216](https://github.com/haexmas/spaex/commit/f92f2160a891e6d7a739f8740683bbdb1e5933a5))
* **spec-026:** spec, plan, and tasks for reliable fragment composition ([987a083](https://github.com/haexmas/spaex/commit/987a0830f190465578b1ad72f0ef1a89fec622d3))
* **spec-027:** spec, plan, and tasks for generic atom-category delivery ([24b49e8](https://github.com/haexmas/spaex/commit/24b49e8538ebb5b00b2aefdcf610a5d044dd4cfd))
