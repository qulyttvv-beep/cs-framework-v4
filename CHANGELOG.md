# Changelog

All notable changes to CS Framework are documented here. This project adheres
to [Semantic Versioning](https://semver.org/).

## [4.2.0] — 2026-09-25

The "studio" release: **CS Studio**, a desktop app in the style of the Claude
desktop app, inside the same single executable. Version 4.1.0 was never
published as a release, so its fixes (below) ship here too.

### Added
- **CS Studio (`cs studio`, or double-click the exe).** A calm dark interface
  (plus a light theme) modelled on the Claude desktop app, with no gradients:
  sidebar with recents and search, serif replies, a centred composer, a model
  picker, and toasts, popovers and modals.
  - **Chat** with streaming markdown, tables, syntax highlighting, file and image
    attachments (sent to vision models), copy / retry, and saved history.
  - **Artifacts**: HTML, SVG and long code blocks open in a side panel with
    live Preview / Code, copy and download. A gallery collects all of them.
  - **Code workspace**: open a project folder to get a file tree, viewer and
    editor, plus an agent that reads, greps, edits and runs commands there.
  - **Built-in browser** with search, reader mode and "Ask CS about this page";
    the model can also browse as a tool.
  - **Computer use**: screenshots (shown inline), mouse, keyboard, scrolling
    and windows. The libraries are bundled in the release binaries, or run
    `cs install computer`.
  - **Tool approvals**: anything that changes something (shell, writes,
    edits, input control) asks *Allow once / Always allow / Deny* first. The
    policy can be changed in Settings.
  - **Connectors (MCP)**: a gallery of common servers, custom commands, and
    one-click import of your Claude Desktop MCP config.
  - **Routines**: prompts that run every N minutes or daily, with a run log.
  - **Settings**: general (theme, accent, font, approvals), providers, models
    and runtimes (installs, Hugging Face downloads), per-model context,
    computer use, about.
- **Providers with genuine free tiers**: Groq, Google Gemini, OpenRouter,
  Cerebras, Mistral, GitHub Models, Hugging Face, NVIDIA NIM and SambaNova,
  plus OpenAI, DeepSeek and Together. Each has a *Get key* link, and its model
  list is discovered automatically. Ollama and LM Studio are detected
  automatically. Any OpenAI-compatible **custom endpoint** works too, with or
  without a key. Pollinations is available as an opt-in, clearly labelled
  keyless option. Keys are never sent back to the UI.
- **One-click local coder**: downloads Qwen2.5-Coder (1.5B / 7B / 14B GGUF) and
  llama.cpp, with background jobs and progress in the app.
- **New 3D app icon**, ray-marched from code (`tools/render_icon.py`) into
  every PNG size plus `cs.ico` and `cs.icns`. It is embedded in the
  executables.
- New `edit` (exact-text replace) and `browse` tools for the coding agent.
- Built-in **CS Echo** demo model, so the app works with nothing installed.
- Tests for the Studio security model, provider streaming through a mock
  OpenAI server, approval allow/deny, the filesystem sandbox, routines, MCP
  and chats. The release workflow now smoke-tests Studio from each binary.

### Security
- Studio binds to `127.0.0.1`. It uses a per-launch session token on every API
  call, a `Host` allowlist (DNS rebinding), an `Origin` check (CSRF), and
  `X-Frame-Options: DENY`. Artifacts render in sandboxed iframes, and the
  browser proxy needs its own token and serves pages with
  `Content-Security-Policy: sandbox`. File access is limited to the opened
  project folder.

### Changed
- **One executable.** The Studio frontend ships inside the PyInstaller binary.
  Double-clicking it on Windows opens Studio in an app window and hides the
  console. Running it from a terminal gives the CLI.
- The app opens in a native window (pywebview), an app-mode Edge / Chrome /
  Chromium window, or the default browser, whichever is available first.
- Multi-model providers: every model of a connected provider appears as
  `provider/model`.
- Release builds target Windows x64, Linux x64 and macOS arm64. The Intel macOS
  runner was dropped because it stalled the release.
- Removed duplicate definitions in `cs.py` (`fetch_json`, `fetch_text`,
  `_find_serve_procs`, `cmd_stop`). `cs stop` / `cs ps` now also find
  servers started from the packaged executable.

### Fixed
- `cs studio` / `cs serve` no longer do a reverse-DNS lookup when they bind,
  which could delay startup by ~35 s on macOS.
- SSE responses send `Connection: close` and close the socket after the
  stream, so readers no longer hang.
- `serve`, `stop` and `studio` no longer trigger the first-run setup wizard.

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
