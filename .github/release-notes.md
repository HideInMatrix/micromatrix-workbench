# Experimental desktop packages

This is an experimental prerelease, not a stable release. Review the known
limitations and the current release-readiness report before using these packages.

- Runtime and tunnels start only after the user clicks Start.
- macOS packages use ad-hoc signing, without Apple notarization. Windows packages
  are not Authenticode-signed. No production signing credentials are required by
  this workflow.
- The build matrix targets macOS arm64/x64, Windows x64 and Linux x64. Successful
  compilation is not a guarantee that installation or all Tunnel providers have
  been validated on those platforms.
- Pending work includes desktop graceful shutdown with an active Tunnel,
  control-plane/proxy trust hardening, OAuth rate limits and comprehensive license
  auditing. Do not deploy these test builds as a public production MCP service.
- Each platform provides installers, a standalone service archive, build metadata
  and SHA-256 checksums. Standalone Unix executables are archived to preserve their
  executable permissions.
