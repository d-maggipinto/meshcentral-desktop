# Contributing

Thank you for helping improve MeshCentral Desktop. This is an unofficial client for MeshCentral,
maintained by CYVELION LTD. Please keep in mind that it is developed and tested on Debian and Debian
based distributions only.

## Reporting a bug

Open an issue with the **Bug report** template and include:

- the app version (window subtitle or *About*),
- your distribution and version, and whether the session is X11 or Wayland,
- your MeshCentral server version (*My Server*, *Check server version*),
- the exact error text or a screenshot, and the steps to reproduce.

Never post passwords, login tokens, server addresses you want to keep private, or screenshots that
show other people's data. For security problems, follow [SECURITY.md](SECURITY.md) instead of
opening a public issue.

## Suggesting a feature

Check [ROADMAP.md](ROADMAP.md) first: the feature may already be planned. Most features mirror a
page or dialog of the MeshCentral web interface. If you ask for one, a screenshot of the web
interface page you mean helps a lot.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Keep changes focused; one feature or fix per pull request.
3. Follow the existing code style: plain Python 3 with GTK 3, no new runtime dependencies unless
   they are packaged in Debian stable. Keep the code compatible with Python 3.11.
4. Use only the documented MeshCentral control channel messages (see
   [docs/PROTOCOL.md](docs/PROTOCOL.md)) and respect the account's permissions (see
   [docs/PERMISSIONS.md](docs/PERMISSIONS.md)). The server enforces permissions; the app should only
   offer what the account may do.
5. Run the unit tests (`python3 -m unittest discover -s tests/unit -v`) and build the package
   (`scripts/build-deb.sh`). If your change touches protocol behaviour, test it against a local
   MeshCentral server as described in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md), never against a
   production server.
6. Update `CHANGELOG.md` and the documentation when behaviour changes.

By contributing you agree that your contribution is licensed under the Apache License 2.0, like the
rest of the project.
