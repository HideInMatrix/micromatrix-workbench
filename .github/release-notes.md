# micromatrix agent v0.5.22

Normal version tags publish automatically as stable releases and GitHub Latest;
tags with a prerelease suffix remain prereleases. Review the known limitations
and the release-readiness report before using these packages. A stable release
label does not imply production signing or that all security work is complete.

- v0.5.21 was blocked before packaging by an Ubuntu CI attempt to start the
  unsupported native Linux MCP. v0.5.22 keeps real UI/browser checks on Ubuntu
  and requires packaged browser/MCP acceptance in every macOS/Windows job;
  Linux desktop support is not re-enabled and native gates are not skipped.

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
  A grant-enabled AppKit fixture has now verified real AX batch mutation and
  independent readback with the new certificate-signed candidate; installed
  0.5.19 and candidate 0.5.20 retain the same already-granted helper identity.
  This is not Blender scene modeling or positive screen-capture acceptance. Windows checks the interactive desktop;
  the UIA/window capture/input helper compiles, but grant-enabled capture/input awaits real-machine acceptance.
- This source revision adds fixed public OAuth origins, Host/Origin validation,
  login/request quotas, bounded expiring grants, instance-bound Tunnel readiness
  and serial health checks. Tailscale cleanup is port/route-owned, not global reset.
- Browser endpoint/origin configuration is available in Plugins. Saving never
  connects or starts Runtime; browser debugging must be explicitly enabled in a
  separate session. Packaged real Chromium batch/readback was verified locally.
- Dependency notices are generated from actual JS inputs and the target Cargo
  graph and retained inside installers; missing upstream notices are reported,
  not silently represented as a completed legal audit. All three native jobs now check strict notice files and real packaged browser
  batches; headless native GUI checks report UNVERIFIED, never a false PASS.
  Real Windows GUI, macOS positive visual input and live provider accounts still
  need acceptance.
  The app checks for stable updates automatically; About offers signed download,
  installation and restart. Runtime/Tunnel stop only after verified download.
  Old versions without the updater require one manual installation first.
- Public assets contain four desktop installers, two macOS updater archives,
  latest.json (embedded signatures) and one combined SHA256SUMS.txt.
  Standalone service archives and build metadata remain in Actions artifacts;
  they are not Release downloads. The desktop still includes its required service
  sidecar. Listed license notices and known limits are bundled inside the app.

- Computer Use now offers approved JavaScript batches in embedded QuickJS/WASM,
  native AX/UIA plus explicit foreground-window images (macOS 14+ / Windows),
  and opt-in DOM/ARIA/image + Playwright on a user-configured loopback browser.
  macOS OCR is local; Windows has no local OCR yet. A disconnected browser
  session must be reconfigured; no browser download or automatic profile access.
  Scripts cannot use Node, shell, arbitrary page.evaluate or implicit permissions.
  Browser connection UI has been verified with the real bundled web application.
  Full native visual capture/input and generic visual task success are not
  established by compile or headless fixture tests.

- Dependency security: MCP SDK 1.32.1 and source-map-js 1.2.2 fix two high-severity advisories. External MCP OAuth tokens and client information retain SDK issuer binding; legacy unbound credentials require one fresh login, without clearing other saved secrets. CI verifies real local CIMD/PKCE and blocks high/critical npm advisories.

- Provider startup is cancellable; Tailscale in-flight CLI drains before owned
  cleanup, and simultaneous Stops share one cleanup. Cloudflare fake-IP/blocked
  7844 failures report targeted diagnostics without publishing an unready URL.
  Local live HTTP2/QUIC acceptance was blocked by the network environment, not
  represented as a successful public connectivity test.
