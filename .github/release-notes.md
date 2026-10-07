# micromatrix agent v0.5.19

Normal version tags publish automatically as stable releases and GitHub Latest;
tags with a prerelease suffix remain prereleases. Review the known limitations
and the release-readiness report before using these packages. A stable release
label does not imply production signing or that all security work is complete.

- Runtime and tunnels start only after the user clicks Start.
- cloudflared 2026.9.3 is bundled; the desktop uses its private copy without an
  executable-path form field. Other tunnel providers still require their clients.
- New macOS packages use a pinned long-lived self-signed code-signing certificate, without Apple notarization; v0.5.18 and earlier used ad-hoc signing. Windows packages
  are not Authenticode-signed. Updater packages use the dedicated Tauri signing
  key; this does not provide Apple notarization or Authenticode signing.
- The build matrix targets macOS arm64/x64 and Windows x64 (Linux desktop support is suspended). Successful
  compilation is not a guarantee that installation or all Tunnel providers have
  been validated on those platforms.
- Computer Use is preinstalled as a Pi MCP plugin; enable its switch instead of
  adding a separate MCP service. It is disabled on fresh installs and still loads
  only after Runtime Start. Enabling permits control actions subject to Runtime
  approval policy; legacy read-only configurations remain read-only until opted in.
- macOS now bundles a separate micromatrix Computer Use.app with the original
  icon and fixed bundle identity. Permission checks and desktop operations use
  this same application through LaunchServices and private local IPC, instead
  of spawning a bare helper under the main application.
- Grant Accessibility to micromatrix Computer Use.app, not just micromatrix
  agent or Blender. Plugins offers Open Permission Settings, Recheck and Locate
  Application. Existing main-app grants do not prove that this new app is
  authorized. Migration from an old ad-hoc build may require one new grant. New builds keep
  the same certificate-bound identity, with an isolated Dev bundle ID; granted
  TCC behavior across upgrades still requires real-machine acceptance. Self-signing
  does not make the app Apple-trusted or notarized.
- Runtime now contains connection configuration and Start/Stop only. Tools,
  Computer Use, external MCP services and Skills are managed on the Plugins
  page; connection help and the tool catalog are collapsed by default.
- macOS arm64 packaging, signatures, native application identity and denial
  paths were verified without requesting OS permission or controlling Blender.
  Grant-enabled desktop interaction and Blender-specific modeling adapters
  remain unvalidated/unimplemented. Windows checks the interactive desktop;
  its existing helper remains unchanged and awaits real-machine acceptance.
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
