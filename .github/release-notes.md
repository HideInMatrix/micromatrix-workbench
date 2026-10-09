# micromatrix agent v0.5.26

## Remote Desktop + ASIL

- New remote-desktop provider returns an explicitly selected display image,
  monitor topology, visible-window layout and the foreground AX/UIA tree over
  the existing authenticated MCP. No VM, separate VNC/RDP listener or video loop.
- AI can combine pixels with native structure, submit approved JavaScript
  batches, click across observed windows and independently observe the result.
  Native semantics, single-window capture, opt-in browser and approved ASIL
  file/command/API providers remain available.
- Display IDs, coordinate spaces and image revisions are validated. Stale
  actions are refused without retry; keyboard input stays in the observed
  foreground application. Secure-field checks are not general privacy redaction.

## Platforms and limits

- macOS 14+ full-display capture uses ScreenCaptureKit and requires Screen
  Recording plus Accessibility for micromatrix Computer Use.app. The fixed
  certificate-bound identity and original icon are retained; no automatic grant.
- Windows x64 uses bounded GDI display capture and UI Automation on the unlocked
  interactive desktop. Protected/hardware-overlay pixels may be unavailable;
  no UAC/secure-desktop access or elevation. Linux desktop support remains off.
- Images are at most 1280px on the longest side and 384 KiB. Window layout and
  foreground controls are bounded, non-atomic evidence, not full application
  internal state. Animations/clocks may trigger stale-observation refusal.
- Local MCP/QuickJS contracts and macOS compilation/permission-denial paths
  passed. Native build gates run on all supported release runners; positive
  whole-display capture/input and GUI installation still need real-machine
  acceptance. Headless checks do not claim GUI success.

## Distribution

- Runtime/Tunnel still start only when the user clicks Start. Retains the latest
  public-outage handling, startup cancellation and user-controlled update flow.
  Stable updates are checked automatically; installation is initiated in About.
- macOS uses a long-lived self-signed certificate, not Apple notarization;
  Windows installers are not Authenticode-signed. Updater packages are signed
  with the dedicated Tauri key. Installer notices preserve known review limits.
- Releases contain desktop installers, macOS updater archives, latest.json and
  a combined checksum file. Standalone services are not public release assets.
