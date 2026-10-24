# GenSprite Windows Setup Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in the current session. The user has approved the linked design and instructed implementation; no further design approval is needed.

**Goal:** Deliver a self-contained Windows installer that connects a chosen local game project to GenSprite in Codex.

**Architecture:** Package the existing stdio server as a console executable, embed it with a digest/version manifest in a windowed setup executable, and use a small shared installer module for safe per-user installation, format-preserving TOML configuration, and an actual stdio MCP handshake. A Tk project picker runs installation off the UI thread.

**Tech Stack:** Existing Python/Pillow/MCP, standard-library Tk/subprocess/path handling, tomlkit for preserving user TOML, PyInstaller for Windows builds.

**Spec:** docs/superpowers/specs/2026-10-24-windows-setup-design.md (approved 2026-10-24).

## Global Constraints

- Local Windows/Codex only; no hosting, remote upload, credentials, or image provider.
- Bundle Python and runtime dependencies; no administrator requirement.
- Preserve unrelated Codex settings and back up changed configuration.
- Each selected project uses its own .gensprite output directory.
- Do not bypass Codex project trust or add art-review gates.
- Keep automated checks in source and exclude tests/demos/sample outputs from delivered artifacts.
- No code signing certificate is configured; disclose unsigned distribution.

## Review Focus

- Existing malformed/large TOML must fail without losing settings.
- Linked directories and changed configuration must not redirect/clobber writes.
- Corrupt executable payload or failed handshake must leave existing configuration intact.
- Paths containing spaces, quotes, and Unicode must round-trip through TOML and subprocess argv.
- Repeated setup must be idempotent and a second project must retain its own store.

## Tasks

### Task 1: Safe local installation and Codex connection

Files: src/gensprite_mcp/installer.py, tests/test_installer.py, pyproject.toml.
Interfaces: prepare_config(existing: bytes | None, executable: Path, project: Path) -> bytes; check_connection(command: list[str], timeout: float = 60) -> dict; connect_project(project: Path, source: Path, expected_sha256: str, version: str, install_root: Path, progress=None) -> InstallResult.

- [ ] Write failing tests for configuration preservation, backups/idempotency, independent stores, bad TOML, corrupt payload, links, failed connection, and concurrent config changes.
- [ ] Implement bounded config parsing with tomlkit, immutable version/digest install paths, a real bounded stdio handshake, atomic writes and rollback-safe configuration.
- [ ] Run focused tests including a real Python-launched MCP; verify failure paths and full accepted paths.

### Task 2: Project-picker installer and packaged release

Files: src/gensprite_mcp/setup_gui.py, scripts/packaged_server.py, scripts/packaged_setup.py, scripts/build_windows.py, tests/test_setup_gui.py.
Interfaces: SetupWindow(root, payload, manifest, install_root); main() displays UI; --self-check --report PATH installs into a temporary project and verifies the actual bundled executable/configuration without touching user settings.

- [ ] Write checks for UI construction, manifest validation and headless self-check behavior.
- [ ] Implement Select project / Connect to Codex / progress / actionable success/error UI and the embedded payload manifest.
- [ ] Add the PyInstaller builder; package console server and windowed setup without retaining sample outputs.
- [ ] Build Windows executables and run the packaged installer's self-check and the normal real MCP workflow against its installed server.

### Task 3: Review, release evidence and documentation

Files: README.md, docs/deployment.md, .github/workflows/ci.yml, scripts/release_check.py if needed.

- [ ] Update Windows install/use instructions and CI artifact build, retaining local-only architecture and trust behavior.
- [ ] Run all source release checks and build/inspect wheel/source archives.
- [ ] Request one independent read-only review; fix concrete findings and rerun affected/full checks as warranted.
- [ ] Rebuild and verify final standalone installer, record results and link the delivered executable.
