# Deploying GenSprite MCP

GenSprite runs as a local stdio MCP server on Python 3.11 or newer. An MCP client starts the process and communicates through stdin/stdout; diagnostics go to stderr. There is no HTTP listener, hosted account, provider API key, or GPU requirement in this server.

The connected AI agent supplies the artwork as native-grid pixel rows, base64 PNGs, or animation frame asset IDs. Clients that negotiate MCP sampling can ask their authoring model to supply structured artwork. Sampling is optional: use `create_pixel_art`, pass `drawing={rows,palette}` to `generate_game_art`, import a PNG with `import_asset`, and pass `frame_asset_ids` or pixel `frames` to `animate_game_art` when sampling is unavailable. Sampling and any model charges are controlled by the client.

## Windows setup for Codex

The local Windows x64 release includes `GenSprite-Setup.exe`. Open it, select **Codex** or **OpenCode**, choose an existing game project folder, then click **Connect project**. Reopen that client in the project. The client's trust and managed policies still apply; setup does not alter trust or tool approval policies.

Python and all server dependencies are bundled. Setup needs no administrator privileges and makes no network calls. The user's connected AI model may still be cloud-based; explicit supplied artwork is processed locally by GenSprite.

The installed runtime is stored at `%LOCALAPPDATA%\GenSprite\versions\<version>-<digest>\GenSpriteMCP.exe`. Project configuration points to that stable installed copy, so the original source checkout or downloaded Setup file is not needed to keep the connected project working. Keep Setup if you want to connect another project later.

Setup writes only the GenSprite transport entry in `<project>\.codex\config.toml`, preserving unrelated settings/comments and existing tool policy. It stores backups of changed configurations under `%LOCALAPPDATA%\GenSprite\backups\<project-identity>`. Assets and history live under `<project>\.gensprite`. Do not point multiple running servers at the same store.

Setup verifies the embedded executable digest, installs an immutable version/digest path, and performs an actual stdio initialization/tool-discovery check using a temporary store. It commits configuration only after that check passes. Invalid/oversized configuration, linked directories, runtime corruption and conflicting edits fail without replacing the existing configuration. A failed connection can leave the verified binary installed; rerun Setup to retry. No demo or sample artwork is retained.

Run Setup again for another project or a new release. Repeated setup with the same release is idempotent. Existing project artwork is retained across runtime updates. Older runtime versions are kept to avoid breaking projects still referencing them.

To disconnect a project, remove its `[mcp_servers.gensprite]` entry from `.codex/config.toml` and reopen Codex. Keep `.gensprite` if you want to preserve assets/history. Remove the per-user installed runtime only after every connected project has stopped using it; no uninstall action deletes game assets automatically.

Build and verify the standalone installer on Windows x64:

```powershell
uv sync --locked --group build
uv run --locked --group build python scripts/build_windows.py
```

The builder packages separate console-server and windowed-setup executables, preserving MCP stdin/stdout. It executes the production sprite/animation/export smoke against the standalone server, then runs the packaged GUI in a hidden self-check. That check covers existing configuration preservation, backups, Unicode/spaced paths, repeated installation, independent project stores and temporary-data cleanup. Only a passing build is copied to `dist\GenSprite-Setup.exe`; `GenSprite-Setup.exe.sha256` records its digest. Generated build intermediates stay under `.tools/windows-build` and are excluded from Python distributions.

The executable is not code-signed. Windows may warn about an unknown publisher. A public signing certificate and public distribution/hosting are future decisions; payload digests alone do not authenticate a publisher.

## Install a built wheel

Build and verify the release from a checkout using uv:

```console
uv sync --locked
uv run --locked python scripts/release_check.py
uv build
```

The release check runs the Python suite with warnings treated as errors, Ruff, and a real stdio MCP smoke. The smoke discovers the production tools, draws two temporary 8x8 poses, assembles an animation from those exact frames, validates outputs, and inspects the exported ZIP and frame timing. Its temporary asset store is deleted on exit. It does not require retained examples, external image providers, or installed game engines.

Install the resulting wheel in a dedicated environment. For the current package version, Windows PowerShell commands are:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install .\dist\gensprite_mcp-1.3.0-py3-none-any.whl
.venv\Scripts\python.exe -m gensprite_mcp --output-dir C:\GenSpriteData
```

On Linux or macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install dist/gensprite_mcp-1.3.0-py3-none-any.whl
.venv/bin/python -m gensprite_mcp --output-dir /absolute/path/to/gensprite-data
```

Use the wheel filename produced by the selected release if its version differs. Launching the command manually waits for MCP input; connect it through your client's stdio-server configuration for normal use. The installed `gensprite-mcp --output-dir <absolute-store-path>` entry point is equivalent to `python -m gensprite_mcp`.

A client configuration using an installed Windows virtual environment looks like this; replace the executable and storage paths with your absolute paths:

```json
{
  "mcpServers": {
    "gensprite": {
      "command": "C:\\Tools\\GenSprite\\.venv\\Scripts\\python.exe",
      "args": ["-m", "gensprite_mcp", "--output-dir", "C:\\GenSpriteData"]
    }
  }
}
```

For Linux or macOS, use the absolute `.venv/bin/python` path and a writable absolute output directory. A stdio client owns the server process lifecycle; no shell wrapper or background web service is needed.

## OpenCode local connection

For an OpenCode v1 game project using this source checkout, add the following entry to its `opencode.json` or `opencode.jsonc`. Merge it into existing `mcp` settings, replacing the paths with your source environment and game project. The command array is executed directly; it does not require shell quoting.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "gensprite": {
      "type": "local",
      "command": [
        "C:\\GenSprite\\.venv\\Scripts\\python.exe",
        "-m", "gensprite_mcp", "--output-dir",
        "C:\\Games\\KnightGame\\.gensprite"
      ],
      "enabled": true,
      "timeout": 60000
    }
  }
}
```

Run `opencode mcp list` from that game folder; GenSprite should report connected. The checked client is OpenCode 1.18.31. Local configuration is described in the [official MCP documentation](https://opencode.ai/docs/mcp-servers/). In v2, put the entry under `mcp.servers`, replace `enabled: true` with `disabled: false`, and use `timeout: {"startup": 60000}`; see the [migration guide](https://opencode.ai/v2/docs/migrate-v1).

Windows Setup supports strict JSON in existing `opencode.json`/`opencode.jsonc`, retaining other client settings and creating recoverable backups. Commented JSONC, trailing commas, duplicate JSON keys, conflicting config files, or malformed settings are refused before any configuration change. Add the example manually when keeping JSONC comments. Existing v2 `mcp.servers` layout is detected and preserved. New setup configurations use the checked v1 layout. Setup checks the real stdio server before writing settings; the client's own connection is checked with its CLI.

## Run in Docker

Build from the repository root:

```sh
docker build -t gensprite-mcp .
docker volume create gensprite-data
docker run --rm -i --network none --mount type=volume,src=gensprite-data,dst=/data gensprite-mcp
```

The image installs the package from `pyproject.toml` and runs as UID/GID `10001:10001`. A named volume preserves the whole `/data` store between process starts. Bind-mounted host directories must be writable by that UID/GID. The build needs access to the Python package index; the shown runtime disables container networking. The Docker build uses the dependency ranges in `pyproject.toml`; the CI source checkout uses `uv.lock`.

Configure Docker as the client's stdio command:

```json
{
  "mcpServers": {
    "gensprite": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--network", "none",
        "--mount", "type=volume,src=gensprite-data,dst=/data",
        "gensprite-mcp"
      ]
    }
  }
}
```

Keep `-i` and omit `-t`: MCP requires a byte stream without terminal formatting. Image build context includes only package sources and package metadata; local assets, virtual environments, Git files, caches, and credentials are excluded.

## Persistent storage and operation

Run one server process per output directory. Jobs belong to that process; a restarted process reports unfinished work as interrupted rather than claiming that outputs succeeded. Clients can poll `check_job_status` and submit new work after an interruption. Cancelling a job changes its reported state; immutable files already written can remain in the store.

Use a local persistent filesystem writable by the server account. Preserve the complete store, including generated images, manifests, animations, exports, job records, imported originals, and `catalog.sqlite3` organization/preset data. Stop the server before copying or restoring a backup. Asset and revision IDs refer to immutable files; editing creates a new asset ID with parent ancestry. File URLs returned by tools are local `file:` URIs, so a Docker client must access the mounted data through Docker or a suitable host bind mount.

No human art-review gate blocks generation, animation, or export. `ready_for_export` means automated technical checks passed for those files. It does not certify artistic quality: the authoring agent remains responsible for deliberate pixel placement, readable silhouettes, consistent characters, palettes, and motion.

Core limits are native canvases of 8..256 pixels per side, 1..32 palette colors, binary alpha, PNG inputs up to 4 MiB, and animations of 1..16 frames. `prepare_sprite` accepts source PNGs up to 4096px per side before explicit downsampling; native imports stay at 256px. Durations are 10..10,000 milliseconds in multiples of 10. Organization lists return at most 200 items; filesystem discovery scans at most 2,000 entries and explicitly marks incomplete totals. Private preset settings are bounded to 64 KiB of JSON. Invalid inputs and tampered source digests fail technical validation.

GenSprite's local processing has no server-side credit meter. Client model subscriptions, token charges, hardware use, and storage still depend on your environment. This package does not use or reproduce SpriteCook's private hosted providers, subscriptions, or billing APIs. Export checks verify file contents, metadata, frame order and timing; game-engine imports and runtime behavior must be checked in the target engine.

## Continuous integration

`.github/workflows/ci.yml` installs locked dependencies and runs the same release check on Ubuntu and Windows with Python 3.11 and 3.12. Each successful job builds and uploads its wheel and source distribution. A Windows x64 packaging job also builds and checks the standalone installer. Docker builds, client-specific sampling, and game-engine execution are separate checks.

## Visual review and named delivery (1.2)

`review_asset` accepts a sprite or animation ID and returns a bounded PNG review board directly through MCP plus factual diagnostics. Vision-capable authoring agents should inspect and refine the master before creating motion, then inspect the animation contact sheet and playback where supported. Review hints are not aesthetic guarantees or additional approval gates.

`build_asset_library` publishes an explicit selection of finished master sprites and their animations under `<store>/library`. Catalog labels produce readable names; stable ID suffixes prevent collisions. The returned `index.html` works directly in a local browser with search, native file links, and user-controlled animation previews. It needs no server or external assets. Call this tool at the end of each finished batch; canonical data and intermediate poses are not reorganized automatically.

The library is a managed delivery copy. Repeated publication retains previous entries and preserves native pixels and timing. Modified managed files, invalid indexes, path links, and conflicting destinations cause an actionable error rather than silent replacement. Back up the complete store as before. Reconnect each installed project with the 1.2 Setup executable to use the new tools; existing installations keep their versioned runtime until explicitly updated.

Library publication accepts 1..200 distinct master IDs at a time. Cumulative limits are 1,000 masters, 20,000 managed files, 256 MiB of managed output, and an 8 MiB index. Each master can have up to 200 published animations. Exceeding limits or incomplete bounded animation discovery produces an explicit error. If a server stops during publication, follow its lock-recovery error only after all processes using that store have stopped; preserve user-modified destinations when resolving conflicts.

Publication stages validated payloads and keeps a bounded journal of before/after hashes and backups until the new index commits. Ordinary replacement failures roll back; the next call recovers an interrupted transaction before loading the index. Recovery refuses to replace destination files that no longer match the known old/new content. Canonical assets remain separate throughout. This protects process-level interruptions; it is not a guarantee against hardware or power-loss corruption.
