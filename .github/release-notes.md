# micromatrix agent v0.5.16

Normal version tags publish automatically as stable releases and GitHub Latest;
tags with a prerelease suffix remain prereleases. Review the known limitations
and the release-readiness report before using these packages. A stable release
label does not imply production signing or that all security work is complete.

- Runtime and tunnels start only after the user clicks Start.
- cloudflared 2026.9.3 is bundled; the desktop uses its private copy without an
  executable-path form field. Other tunnel providers still require their clients.
- macOS packages use ad-hoc signing, without Apple notarization. Windows packages
  are not Authenticode-signed. Updater packages use the dedicated Tauri signing
  key; this does not provide Apple notarization or Authenticode signing.
- The build matrix targets macOS arm64/x64 and Windows x64 (Linux desktop support is suspended). Successful
  compilation is not a guarantee that installation or all Tunnel providers have
  been validated on those platforms.
- Computer Use uses one semantic proxy with macOS Accessibility and Windows UI
  Automation native backends; actions are disabled by default and require the
  existing tool approvals. Native Windows interaction awaits real-machine acceptance.
- Pending work includes desktop graceful shutdown with an active Tunnel,
  control-plane/proxy trust hardening, OAuth rate limits and comprehensive license
  auditing. These limits still apply to formally published releases.
  The app checks for stable updates automatically; About offers signed download,
  installation and restart. Runtime/Tunnel stop only after verified download.
  Old versions without the updater require one manual installation first.
- Public assets contain four desktop installers, two macOS updater archives,
  latest.json (embedded signatures) and one combined SHA256SUMS.txt.
  Standalone service archives and build metadata remain in Actions artifacts;
  they are not Release downloads. The desktop still includes its required service
  sidecar. Listed license notices and known limits are bundled inside the app.
