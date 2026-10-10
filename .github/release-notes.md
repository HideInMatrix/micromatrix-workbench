# micromatrix agent v0.5.31

## Changes

- Warm native Rust dependency caches on relevant master pushes without signing
  or compressing installers. Later release tags can reuse the default-branch
  caches; native macOS ARM64, Intel x64 and Windows x64 runners remain separate.
- Build only the desktop Rust library output and tune the release profile for
  shorter compilation. Strip Rust symbols without stripping the Node SEA or
  Computer Use native helpers; retain panic/unwind and signing safeguards.
- Minify the embedded JavaScript service while retaining function/class names.
- Store complete dependency license text once in the companion text inventory;
  schema-2 JSON retains sources, hashes, review warnings and exact UTF-8 byte
  ranges. No required license/copyright text is removed.
- Stop producing redundant standalone service archives by default. Explicit
  manual builds can request a separate internal artifact; public Release assets
  remain desktop installers, signed updates, latest.json and checksums.
- Retain `@ouvren/computer-use@0.1.1` prebuilt helpers, existing Runtime Stop and
  process cleanup fixes, managed MCP integration and all permission boundaries.

## Validation

- TypeScript and Vue checks, frontend, service, native Rust and ARM64 development
  installer builds pass locally. GitHub Actions configuration passes actionlint.
- CI-matching Node 22.23.3 was used for bundled CJS, isolated SEA without
  node_modules, and SEA inside the actual Tauri app: nine MCP tools, JSON
  observation/actions, read-only gates, secret redaction, stale-observation
  rejection, embedded QuickJS isolation and Playwright lazy loading were checked.
- Control-plane/static frontend checks retain default-stopped Runtime and hostile
  Origin rejection. Local app deep/strict codesign, DMG checksum and updater
  signature/signed-version verification pass.
- All 678 complete notice texts for 437 dependency records round-trip to their
  original SHA-256 hashes. Packaging checks cover optional archive separation,
  stale archive cleanup and checksum/signature/signed-version tamper rejection.
- Warm-dependency host recompilation was about 23% faster on the local ARM64
  machine. CI cache-hit rate, total duration and final signed package sizes are
  platform-specific; no fixed release-time improvement is guaranteed.
- Intel/Windows GUI interaction and low-version macOS behavior still require
  real-machine acceptance testing. Installer builds and production signing are
  performed by CI, not claimed complete by these local checks.

## Compatibility and distribution

- **macOS now requires 13.0 or newer**, matching the npm helper deployment target.
  Whole-display/window visual capture still requires macOS 14+, Screen Recording
  and helper Accessibility permission. Windows x64 requires an unlocked
  interactive desktop; Linux desktop remains unsupported.
- Retain application identifiers, original icons, saved configuration, pinned
  macOS/helper certificate requirements and updater signing identities. Helpers
  are rewrapped/re-signed for the host's development or release identity.
- Runtime and tunnels still start only after clicking Start. Users initiate
  update installation from About.
- macOS uses a long-lived self-signed certificate without Apple notarization;
  Windows installers are not Authenticode-signed. Tauri update packages retain
  their dedicated signatures.
- Public releases contain desktop installers, macOS updater archives, latest.json
  and checksums, not standalone service archives.
