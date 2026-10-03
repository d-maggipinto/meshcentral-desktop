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

## Verifying a download

Every release since 2.25.1 is built by GitHub Actions with a signed build provenance attestation
(Sigstore). Check that a package was built from this repository:

```bash
gh attestation verify meshcentral-desktop_<version>_all.deb --repo d-maggipinto/meshcentral-desktop \
  --signer-workflow d-maggipinto/meshcentral-desktop/.github/workflows/ci.yml --source-ref refs/tags/v<version>
sha256sum -c SHA256SUMS --ignore-missing
```

The Windows files (since 2.26.0) are covered the same way (`gh attestation verify
MeshCentralDesktop-<version>-setup.exe --repo d-maggipinto/meshcentral-desktop`; on Windows,
`Get-FileHash` shows the SHA-256 to compare with `SHA256SUMS`). They are not Authenticode code-signed
yet.

The workflow pins every action to a commit SHA, gives the build a read-only token and only the
release job write access. The job that builds the Windows installers runs no third-party server code
(the MeshCentral server used to test the app runs in a separate job, installed from a lockfile without
install scripts), and only version tags on `main` are released. Published releases are immutable:
their files cannot be replaced afterwards.

The in-app updater downloads only this project's release files from GitHub over HTTPS, checks them
against the release's `SHA256SUMS`, and checks them again right before the installer runs.

## Scope notes

- The app stores passwords only in the system keyring (Windows: Credential Manager), and only when
  *Remember password* is ticked.
- Secrets the app copies for you (2FA secret, backup codes, login-token passwords) are never sent to a
  remote device by clipboard sync.
- The installed package contains no test code. Development tests turn off TLS verification only
  for a local test server on 127.0.0.1.
