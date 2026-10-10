# Third-party notices

## ASIL softwaregen

- Project: <https://github.com/sharryXR/ASIL>
- Reference commit: `ca7706c87a0b1184c99623691adafed7693e25d3`
- Authors: Rui Xie and Lu Chen, Shanghai Jiao Tong University
- Code license: Apache-2.0
- Changes: TS/Zod port of softwaregen contracts, declarative mapping, audit and deterministic generation; product-specific permission grants and bounded transports.

Desktop/internal service distributions carry the exact Computer Use npm dependency's upstream license, data terms and attribution/modification notice, copied from its `third_party/asil/` directory. No duplicate local notice copies are maintained. Upstream JSON examples/fixtures are not retained; no upstream Python Agent/runtime or benchmark dataset is shipped.

## Pi Agent Harness

- Project: <https://github.com/earendil-works/pi>
- Version: `0.87.1`
- Copyright: Copyright (c) 2025 Mario Zechner
- License: MIT

The complete upstream license is stored at `third_party/pi/LICENSE`.

## cloudflared

- Project: <https://github.com/cloudflare/cloudflared>
- Version: `2026.9.3`
- Copyright: Cloudflare, Inc.
- License: Apache-2.0

The upstream license is stored at `third_party/cloudflared/LICENSE` and included in desktop resources.
Official release assets and their SHA-256 digests are pinned in `scripts/cloudflared-manifest.json`.

## Computer Use npm package

- Package: `@ouvren/computer-use@0.1.1`
- Project: <https://github.com/HideInMatrix/computer-use>
- License: Apache-2.0

Adapters and native helpers come from the locked npm package, not a local source workspace. Desktop/internal-service packaging copies its LICENSE, THIRD_PARTY_NOTICES and ASIL/automation notices directly from the installed dependency. macOS helpers are rewrapped/re-signed with the host's build-channel identity; there is no local native-source fallback.

## Universal Computer Use dependencies

The restricted JavaScript batch engine uses quickjs-emscripten 0.32.0 and its QuickJS WebAssembly runtime (MIT; notice copied from the Computer Use npm dependency's `third_party/automation/QUICKJS_LICENSE`). No Node.js host globals are exposed to scripts. Browser integration uses playwright-core 1.63.0 (Apache-2.0; the Computer Use npm dependency's `third_party/automation/PLAYWRIGHT_LICENSE` and Playwright's distributed third-party notices). The packaged runtime includes Playwright library assets but no browser binaries, user profiles or Python runtime. Tactile/UFO/OmniParser/Screen2AX were architectural references only; their code or model weights are not shipped.

## Build-derived dependency notices

Installers carry `notices/dependencies/DEPENDENCIES.json` (names, locked versions,
declared SPDX, upstream source and notice hashes), `DEPENDENCY_LICENSES.txt`, and
`SOURCE_AVAILABILITY.txt` for unchanged MPL dependency source archives. Rust
standard-library copyright notices are copied from the selected compiler
distribution, with a version/commit/hash-bound rust-docs component fallback
for minimal CI installations. These are installer/internal-service resources, not
additional public Release assets.

The inventory uses actual esbuild/Vite npm modules, explicitly embedded QuickJS
WASM/copied Playwright resources and a conservative target Cargo resolution
graph. Notice files missing from upstream archives use reviewed, version/commit/hash-
bound supplemental records. objc2 preserves upstream SDK policy; sigchld and
objc2 standard MIT text is explicitly distinguished from upstream declarations.
No copyright holder/year is invented. For standardwebhooks 1.1.1 the JavaScript
library's MIT notice at its exact npm git commit is retained in
`third_party/dependencies/`; the monorepo root's different license is not used.
Pi chord 0.87.1 is part of the same reviewed Pi release. data-uri-to-buffer 4.0.1
ships its full MIT notice in README and that exact section is preserved.

This inventory is not a completed legal audit: supplemental upstream declarations,
prebuilt cloudflared transitive modules, WASM toolchain runtime and native SDK
obligations remain review items. Inspect `missingNotices`/`reviewWarnings` before
claiming comprehensive redistribution compliance.
