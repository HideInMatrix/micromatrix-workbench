# micromatrix agent v0.5.30

## Changes

- Replace the local Computer Use source workspace with the locked
  `@ouvren/computer-use@0.1.1` npm dependency. Desktop builds use its prebuilt
  macOS ARM64, macOS Intel x64 and Windows x64 helpers; no Swift/C# source
  compilation or local-source fallback is performed by workbench.
- Remove legacy standalone ASIL and Computer Use development/manual commands.
  Adapter generation and standalone usage belong to the separate Computer Use
  project. The application retains its managed built-in MCP integration.
- Copy Computer Use, ASIL and automation notices directly from the installed npm
  dependency instead of maintaining duplicate local copies.
- Retain the upstream Runtime Stop fixes, queued-start cancellation, process-tree
  cleanup and WebKit request cancellation/error handling.

## Validation

- TypeScript and Vue checks, frontend and embedded service builds pass locally.
- Source, compiled JS, bundled CJS and an isolated Node SEA were checked for MCP
  initialization, nine tools, JSON observation, read-only gates, secret redaction,
  action verification and/or QuickJS host-global isolation.
- All three npm native artifacts were checked for their expected architectures;
  both macOS bundles pass code-signature verification. The copied helper and
  npm-owned notice files were verified, and the release-signing guard still
  rejects an ad-hoc fallback.
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
