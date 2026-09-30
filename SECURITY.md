# Security policy

## Supported versions

Security fixes are made for the latest release only.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Report them privately, either through
GitHub's [private vulnerability reporting](https://github.com/d-maggipinto/meshcentral-desktop/security/advisories/new)
or by email to d.maggipinto@cyvelion.co.uk.

Include the app version, what an attacker could do, and the steps to reproduce. You will get an
answer as soon as possible, and credit in the release notes if you wish.

Problems in MeshCentral itself (the server, the agent or the web viewer) should be reported to the
[MeshCentral project](https://github.com/Ylianst/MeshCentral/security).

## Scope notes

- The app stores passwords only in the system keyring, and only when *Remember password* is ticked.
- The rig test scripts in `tests/rig/` turn off TLS verification on purpose, for a local test
  server on 127.0.0.1. They are not part of the installed package.
