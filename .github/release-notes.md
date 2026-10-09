# micromatrix agent v0.5.27

## Changes

- Relocate the Tauri desktop host from `src-tauri` to `apps/desktop`, alongside
  the web UI and Node service. Update development, packaging, resource paths
  and CI cache layout; keep the existing npm commands.
- Simplify README to the application name, purpose, installation and open-source
  acknowledgements. Detailed architecture and Computer Use documents remain.
- Remove project-owned test directories, smoke scripts, fixtures and test-runner
  dependencies. CI retains compilation, dependency/license checks and release
  signature integrity, not automated behavioral regression.

## Compatibility and distribution

- Retain application identifiers, original icons, saved configuration and pinned
  macOS/helper and updater signing identities.
- Runtime and tunnels still start only after clicking Start. Updates are checked
  automatically; users initiate installation from About.
- Existing Remote Desktop + ASIL capabilities are unchanged. macOS whole-display
  capture requires macOS 14+, Screen Recording and helper Accessibility permission.
  Windows x64 requires an unlocked interactive desktop; Linux desktop remains off.
- macOS uses a long-lived self-signed certificate without Apple notarization;
  Windows installers are not Authenticode-signed. Tauri update packages retain
  their dedicated signatures. This release does not replace real-machine testing.
- Public releases contain desktop installers, macOS updater archives, latest.json
  and checksums, not standalone service archives.
