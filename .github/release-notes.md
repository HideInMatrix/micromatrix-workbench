# micromatrix agent v0.5.28

## Changes

- Stop disconnects MCP ingress and active connections immediately, cancels Bash
  and pending approvals, and force terminates owned MCP process trees and tunnel
  processes before waiting for cleanup. The local control service remains
  available to start Runtime again.
- Cancel queued startup requests when Stop is requested, preventing a delayed
  Start from running after cancellation. Stopping also works during an offline
  public health check or an unfinished MCP handshake.
- Normalize WebKit fetch deadline errors, including response-body cancellation.
  If the Stop response is lost, confirm Runtime state before showing an error.
  The local Stop response deadline is reduced from 20 seconds to 5 seconds;
  it does not delay termination.

## Validation

- TypeScript and Vue type checks, frontend build and embedded service build pass.
- Twelve local regression checks cover offline startup and running Stop, queued
  startup cancellation, active Bash cancellation, listener teardown, owned
  process trees, and fetch cancellation/error reporting.
- Production web UI checks confirm a real 30-second Bash command is terminated,
  the MCP port closes, Start becomes available again, and a lost Stop response
  is confirmed from server state. macOS and Windows installers are built by CI.

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
