# Changelog

All notable changes to CS Framework are documented here. This project adheres
to [Semantic Versioning](https://semver.org/).

## [4.1.0] — 2026-09-25

The "revival" release: bug fixes, real packaging, standalone binaries, and CI.

### Added
- **Standalone binaries.** `cs.spec` builds a single-file executable
  (`cs.exe` on Windows, `cs` on Linux/macOS) with PyInstaller. A `Release`
  GitHub Actions workflow builds and publishes Windows, Linux, and macOS
  (Intel + Apple Silicon) binaries with SHA-256 checksums on every `v*` tag.
- **Packaging.** `pyproject.toml` exposes a `cs` console entry point, so the
  framework is installable with `pipx install git+…` or `pip install .`.
- **Continuous integration.** `CI` workflow runs the syntax check, `selftest`,
  and a new `pytest` suite (`tests/`) across Linux/macOS/Windows on
  Python 3.9–3.12.
- **`--version` / `cs version`** to print the version and exit.
- New first-class subcommands wired to existing handlers:
  `connect`, `pull`, `ps`, `rm`, `platforms`.

### Fixed
- **Many subcommands were unreachable.** `main()` used a hand-written argument
  parser that omitted ~25 commands it then tried to dispatch
  (`menu`, `health`, `hex`, `rig`, `stop`, `screen`, `venvs`, `locate`,
  `run-agent`, `auto-ctx`, the computer-use commands, …), so they failed with
  "invalid choice". The CLI now has a single source of truth (`build_cli()`),
  and a regression test asserts every command is dispatched.
- **Empty code-mode tool descriptions.** `TOOLS_HEADER` was built before
  `TOOLS_SPEC` existed, so the coding agent's tool list was always blank. The
  spec is now defined first, with a real description for every tool.
- **Packaged binary lost its data.** The portable `cs_data/` directory was
  keyed off `__file__`, which points inside PyInstaller's temporary extraction
  directory — data never persisted. It now keys off the executable's own
  directory when frozen. Self-install, background `serve`, and `export` are
  likewise frozen-aware.
- **First-run setup blocked non-interactive use.** Running any command on a
  fresh install forced the interactive wizard, hanging CI/pipes and prompting
  for hundreds of MB of pip installs. Setup is now skipped for read-only
  commands and never prompts or auto-installs when there is no TTY.
- Removed a duplicated config-defaults block and corrected the version badge.

### Changed
- Version bumped to `4.1.0` (codename `hex-4.1`); README documents binary
  downloads, `pipx` install, building from source, and testing.
