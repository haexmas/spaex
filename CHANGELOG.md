# Changelog

## [5.4.1](https://github.com/haexmas/spaex/compare/v5.4.0...v5.4.1) (2026-10-13)


### Bug Fixes

* **release:** bump uv.lock in the release commit itself ([05b52e6](https://github.com/haexmas/spaex/commit/05b52e6182b86c6e726e5f3ac83c0887f5a3c9d3))

## [5.4.0](https://github.com/haexmas/spaex/compare/v5.3.2...v5.4.0) (2026-10-13)


### Features

* **local-scope:** add and remove molecules in local scope ([9462976](https://github.com/haexmas/spaex/commit/946297601b05e9439d99b339c27d6182a3026887))
* **local-scope:** add overlay model, schema and git exclude block ([dc9784f](https://github.com/haexmas/spaex/commit/dc9784f738e11607fb53b917972e0cce52448e9e))
* **local-scope:** compose local behavior rules and bump bootstrap block to v3 ([e2ab67e](https://github.com/haexmas/spaex/commit/e2ab67edad53c3f7a392baa7f6d115cb64510ea1))
* **local-scope:** label scope in status, trace and constitution show ([7e11db3](https://github.com/haexmas/spaex/commit/7e11db3ef53096ac9ee9c64126820780ac3cc911))
* **local-scope:** plan and publish local scope during install ([cc0e43f](https://github.com/haexmas/spaex/commit/cc0e43f6343a2185b7185f869f9ad5edab4e6daf))


### Bug Fixes

* **cli:** forward reinstall controls for local remove ([a383716](https://github.com/haexmas/spaex/commit/a383716b6c7161e670f4199835d3181cade91118))
* **local-scope:** address CodeRabbit review findings ([d28cce7](https://github.com/haexmas/spaex/commit/d28cce7be689be5076b95f498623737c7bf212da))
* **local-scope:** guard ignored spaex side effects ([eb2c98d](https://github.com/haexmas/spaex/commit/eb2c98dec17d472b0853b56058a38296b0e96629))
* **local-scope:** keep shadowed overlay, project-owned files and crash convergence ([7711feb](https://github.com/haexmas/spaex/commit/7711feb957d294fcf4d95e8819b36834e5c16077))
* **local-scope:** restore git index after guarded hooks ([184667e](https://github.com/haexmas/spaex/commit/184667eb0733e2c3bde695a3b352bfa21a754816))
* **tests:** make local scope checks portable ([9bd2d7c](https://github.com/haexmas/spaex/commit/9bd2d7c7a705c05872a9f4c54358a644fea1aa8e))


### Documentation

* **local-scope:** document local scope and align spec 029 artifacts with the implementation ([c957278](https://github.com/haexmas/spaex/commit/c9572787e2c04080d8c13c638b84c60f0857e2c7))
* **spec:** add tasks for spec 029 local molecule scope ([68c9a47](https://github.com/haexmas/spaex/commit/68c9a476773be11221e4b6c9f2051b56bc0668d0))

## [5.3.2](https://github.com/haexmas/spaex/compare/v5.3.1...v5.3.2) (2026-10-13)


### Bug Fixes

* **cli:** keep skill_installation policy across add and remove ([a81b163](https://github.com/haexmas/spaex/commit/a81b16392305a90364a962681a24c04fae4267e3))
* **cli:** let spaex remove forward Spec Kit and hook controls ([7ebc86a](https://github.com/haexmas/spaex/commit/7ebc86a1e67d237515cd5399c64c40316352fa40))

## [5.3.1](https://github.com/haexmas/spaex/compare/v5.3.0...v5.3.1) (2026-10-12)


### Bug Fixes

* **speckit:** bootstrap repos without .specify before integration install ([8ceac58](https://github.com/haexmas/spaex/commit/8ceac5884bb410181acfc2dcb2d93671944cb704))


### Documentation

* **speckit:** document bootstrap agent-tool flag ([ac8bcf0](https://github.com/haexmas/spaex/commit/ac8bcf078d18f95615e84cc963de537f3c124e7a))

## [5.3.0](https://github.com/haexmas/spaex/compare/v5.2.3...v5.3.0) (2026-09-28)


### Features

* **manifest:** make molecule version authoritative ([255bd42](https://github.com/haexmas/spaex/commit/255bd42e11ba46745ea725f9c3ca0536f8e9d950))

## [5.2.3](https://github.com/haexmas/spaex/compare/v5.2.2...v5.2.3) (2026-09-25)


### Bug Fixes

* **ci:** auto-sync uv.lock on the release-please PR branch ([0e0e16d](https://github.com/haexmas/spaex/commit/0e0e16d1c5680d422473af66be2621b9085d6877))
* **ci:** dispatch release.yml instead of calling it as a reusable workflow ([dde84ae](https://github.com/haexmas/spaex/commit/dde84aee2761d87e89a05e45d8ec36b5bbd6805c))
* sync uv.lock with pyproject.toml version (5.2.1 -&gt; 5.2.2) ([c2ca37a](https://github.com/haexmas/spaex/commit/c2ca37adecff2198c2eb93b1250d961d0d4d5a32))

## [5.2.2](https://github.com/haexmas/spaex/compare/v5.2.1...v5.2.2) (2026-09-24)


### Bug Fixes

* refresh Spec Kit bootstrap and bundled workflow with current specify-cli ([7bec792](https://github.com/haexmas/spaex/commit/7bec79268fa560b52a01592f2221571b0625bdd1))
* sync uv.lock with pyproject.toml version (5.2.0 -&gt; 5.2.1) ([e0fef9a](https://github.com/haexmas/spaex/commit/e0fef9afdf801c32701b0893aaae8dcb35835ea2))

## [5.2.1](https://github.com/haexmas/spaex/compare/v5.2.0...v5.2.1) (2026-09-24)


### Bug Fixes

* **ci:** chain PyPI publish off release-please outputs ([bed46be](https://github.com/haexmas/spaex/commit/bed46be72cc09f7e9092649ca845a56763412d9d))
* **ci:** synchronize uv lockfile with package version ([1e6ec05](https://github.com/haexmas/spaex/commit/1e6ec05752be771e46eeabb5caf021d8a93ac5f4))

## [5.2.0](https://github.com/haexmas/spaex/compare/v5.1.2...v5.2.0) (2026-09-23)


### Features

* **spec-018:** consumer-controlled skill_installation and spaex skills commands ([ff2277f](https://github.com/haexmas/spaex/commit/ff2277fbcb6cda14cc7f56e0366f473be09c3342))
* **spec-018:** structured external skill references (Phases 2-4) ([422718b](https://github.com/haexmas/spaex/commit/422718ba2f9df50fa7d89e14cf372652070dbfe9))
* **spec-028:** foundational pin-flattening, path-ownership and generation-consistency helpers ([78070c8](https://github.com/haexmas/spaex/commit/78070c8aad65cde1989e700e0176d1926c1d9b3b))
* **spec-028:** implement spaex status (Phase 3, User Story 1) ([5793fd8](https://github.com/haexmas/spaex/commit/5793fd863754edc07cc96d83d1c450817cad6100))
* **spec-028:** implement spaex trace path resolution and CLI (T023-T028) ([9c3b541](https://github.com/haexmas/spaex/commit/9c3b541cd060a47fe2d589d28fdbf283e6015ae0))
* **spec-028:** populate spaex status drift detection (Phase 6, US4) ([fa990e4](https://github.com/haexmas/spaex/commit/fa990e4f8201b68b8818f8b3a55fc788cc7354bf))


### Bug Fixes

* **ci:** keep uv lockfile synchronized ([4b487f1](https://github.com/haexmas/spaex/commit/4b487f1d26f3e28d0282b71c7ba8aa170a899d0b))
* **spec-028:** address status review findings ([578a754](https://github.com/haexmas/spaex/commit/578a75489275f5228c7199ead018965f6bd4ede5))
* **spec-028:** address trace review findings ([ab93759](https://github.com/haexmas/spaex/commit/ab9375982679a721d87773bea6e8c32b3859c6c1))


### Documentation

* add docstrings to behavior trace, install lock, and test helpers ([eb57e74](https://github.com/haexmas/spaex/commit/eb57e748b4ce75e454cdf866923dc1fe8ebe2320))
* close roadmap Phase B without a spec, record Phase C's actual spec number ([f193576](https://github.com/haexmas/spaex/commit/f1935768e8f8cbab0e73444200925738af8e7ff5))
* remove roadmap Phase E, no longer wait for Phase D to decide ([2366d92](https://github.com/haexmas/spaex/commit/2366d9251029fe2bd5ce7d0eb5bf3bbdecc017ae))
* **spec-018:** align external skill documentation ([2c84eee](https://github.com/haexmas/spaex/commit/2c84eeea05b3261a7bb3cdc3208198d8bf4b6452))
* **spec-028:** address PR review findings ([7ce56bd](https://github.com/haexmas/spaex/commit/7ce56bdb0f03d151e0cae55c1311a402a71998c0))
* **spec-028:** polish and close out composition status and provenance query ([5795844](https://github.com/haexmas/spaex/commit/579584434202d8c6416cc78adcf77bd28ed34776))
* **spec-028:** spec, plan, and tasks for composition status and provenance query ([269a6e1](https://github.com/haexmas/spaex/commit/269a6e14c270470f6c1e398a123a41b4de790386))

## [5.1.2](https://github.com/haexmas/spaex/compare/v5.1.1...v5.1.2) (2026-09-21)


### Documentation

* **plans:** bring plan status up to date and drop presets ([a8793c8](https://github.com/haexmas/spaex/commit/a8793c854545e224285f0c8e1d5b14e80b5cbaac))

## [5.1.1](https://github.com/haexmas/spaex/compare/v5.1.0...v5.1.1) (2026-09-19)


### Bug Fixes

* **ci:** address pull request review findings ([0a8c4d2](https://github.com/haexmas/spaex/commit/0a8c4d295e9973043a43f1e9c95ac99d4030625f))
* **release:** let manual dispatch target main via a version input ([1564488](https://github.com/haexmas/spaex/commit/1564488979b7c08e1a84aa42dc79319f0a99f5dd))
* **speckit:** repair drifted claude/codex integrations instead of skipping them ([7a24af9](https://github.com/haexmas/spaex/commit/7a24af97ffe1e98ea72212bd957eb0a585366ff8))

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
