# GenSprite MCP

GenSprite is a local sprite-production toolkit that AI agents use through the **Model Context Protocol (MCP)**. Your AI agent creates the artwork and animation poses. GenSprite turns that artwork into pixel-accurate sprites, refines images, assembles animations, preserves asset history, organizes projects, and exports reusable files for games.

**Current release: 1.2.0, with 65 MCP tools.** The Windows installer connects GenSprite to Codex without requiring a separate Python installation.

GenSprite runs on your computer over **stdio**: Codex starts a local process and communicates through its standard input and output. You do not need a server URL, port, browser dashboard, hosted account, GPU, or image-provider API key for GenSprite. There is no bundled AI image model. Your connected agent supplies pixels, PNGs, or animation frames; clients that support MCP sampling can also ask their model to author artwork through that optional path.

GenSprite processes supplied artwork locally. Your AI client may still use a cloud model and send prompts or reference images to its provider. Installing a local MCP does not make the AI client itself offline.

## Contents

- [Choose an installation method](#choose-an-installation-method)
- [Install on Windows with Setup](#install-on-windows-with-setup)
- [Install from source](#install-from-source)
- [Install a Python wheel](#install-a-python-wheel)
- [Confirm the connection and create your first sprite](#confirm-the-connection-and-create-your-first-sprite)
- [Review and browse assets](#review-and-browse-assets)
- [Connect another project](#connect-another-project)
- [Files, storage, and backups](#files-storage-and-backups)
- [Update or remove GenSprite](#update-or-remove-gensprite)
- [Troubleshooting](#troubleshooting)
- [Available workflows and limits](#available-workflows-and-limits)
- [Build a Windows installer](#build-a-windows-installer)
- [Developer release checks](#developer-release-checks)

## Choose an installation method

| Method | Best for | What you need |
| --- | --- | --- |
| **Windows Setup - recommended for Codex users** | Connect an existing project through a folder picker | Windows x64, Codex, and `GenSprite-Setup.exe` |
| **Source installation** | Work on GenSprite or use a Python-based local MCP | Complete source checkout, uv, and Python 3.11 or newer; uv can provide Python |
| **Python wheel** | Use a packaged Python release without keeping the source checkout | Python 3.11 or newer and the release `.whl` file |

The Windows installer has been checked on Windows 11 x64. Source installation also provides the platform-independent Python server; the Windows `.exe` is specifically for Windows x64.

You need a local MCP-capable client to use the tools. The automatic installer currently configures **Codex on Windows**. Other clients need their own stdio configuration. Installing GenSprite does not install Codex, provide a model account, or change the client's trust and approval policies.

This project is currently distributed locally. The steps below refer to files you already have; there is no public download service assumed by this guide.

## Install on Windows with Setup

### 1. Locate the installer

In the prepared GenSprite project, open:

```text
C:\GenSprite\dist\GenSprite-Setup.exe
```

If your copy lives elsewhere, open its `dist` folder instead. If someone gave you the standalone installer, you can run that copy directly.

A source-only checkout may not contain `dist`, because generated release files are excluded from version control. In that case, use [source installation](#install-from-source) or [build the installer](#build-a-windows-installer). A README or source archive alone does not include the executable.

The installer bundles the server's Python runtime and dependencies. End users do not need to install Python or uv, activate an environment, open a terminal, or run a separate model server.

### 2. Prepare your game project folder

Create or choose the folder you normally open in Codex, for example:

```text
C:\Games\KnightGame
```

The folder must already exist. It can contain your game files or be an empty new project. Select the **project root**, not a `.codex`, `.gensprite`, or `dist` subfolder.

Use an ordinary local folder that your Windows account can write to. The installer rejects drive roots, symbolic links, and Windows reparse-point paths. The source checkout and game project can be in separate folders.

### 3. Open Setup

Double-click `GenSprite-Setup.exe`.

The current installer is **unsigned**. Windows may display an unknown-publisher or security prompt. Confirm that the file came from a source you trust before choosing to run it. Setup does not require administrator privileges.

For an optional integrity check, run these commands in PowerShell from the release folder:

```powershell
Get-FileHash .\GenSprite-Setup.exe -Algorithm SHA256
Get-Content .\GenSprite-Setup.exe.sha256
```

Compare the hexadecimal digest in both outputs. A matching checksum checks file integrity; it does not authenticate the publisher.

### 4. Connect the folder to Codex

In the **GenSprite - Connect to Codex** window:

1. Click **Choose folder...**.
2. Select your game project root.
3. Check that the displayed folder is correct.
4. Click **Connect to Codex**.
5. Wait for the connection check to finish.

A successful installation reports:

```text
Connected. GenSprite is ready with 65 tools.
```

Setup copies a verified server executable into your Windows user profile, starts it to check the real MCP connection, and writes the project's Codex configuration after that check succeeds. Existing unrelated settings and comments are preserved. Changed existing configuration is backed up automatically. Setup does not generate sample artwork.

If Setup reports an error, use its message and the [troubleshooting table](#troubleshooting) before retrying. Do not delete your project configuration or asset store to force installation.

### 5. Reopen Codex in the selected project

Close and reopen the Codex session for that folder, or reload the client so it rereads MCP configuration. Open the **same project root** you selected in Setup. Accept Codex's project-trust prompt if it appears.

Codex reads project configuration from `.codex/config.toml` for trusted projects. Its own trust rules and managed settings still apply. See the [official Codex MCP configuration guide](https://learn.chatgpt.com/docs/extend/mcp).

GenSprite starts when the client connects to it. You do not need to keep Setup open or manually launch a background server.

### 6. Confirm it is available

Ask Codex:

> Check whether the GenSprite MCP server is connected. List its available sprite and animation tools without creating assets.

Then follow [the first-sprite steps](#confirm-the-connection-and-create-your-first-sprite).

### What Setup installs

| Location | Purpose |
| --- | --- |
| `%LOCALAPPDATA%\GenSprite\versions\<version>-<digest>\GenSpriteMCP.exe` | Shared, versioned local server runtime |
| `<your-project>\.codex\config.toml` | Project-specific Codex MCP configuration |
| `<your-project>\.gensprite` | Asset, animation, revision, job, and export store; populated as the server is used |
| `%LOCALAPPDATA%\GenSprite\backups\<project-identity>` | Backups made when existing configuration changes |

For a Setup installation, the configured runtime is the installed copy in your user profile. The original source folder and Setup executable are not required to keep that connected project working. Keep Setup if you want to connect additional projects later.

## Install from source

Use this method to edit GenSprite or run its Python server directly. The following commands use Windows PowerShell and assume the complete source project is at `C:\GenSprite`. Replace that path if necessary.

### 1. Install uv

If `uv --version` already works, continue to the next step. Otherwise, install uv using the [official uv installation guide](https://docs.astral.sh/uv/getting-started/installation/). On Windows with WinGet:

```powershell
winget install --id=astral-sh.uv -e
```

Reopen PowerShell, then confirm:

```powershell
uv --version
```

This prepared checkout may also have a local uv executable at `.tools\uv\uv.exe`. Use that full executable path in place of `uv` if you are maintaining this checkout without a global uv installation.

### 2. Install the locked environment

Make sure the source folder contains `pyproject.toml`, `uv.lock`, and `src\gensprite_mcp`.

```powershell
Set-Location 'C:\GenSprite'
uv sync --locked --python 3.12
uv run --locked gensprite-mcp --help
```

uv creates `.venv`, installs the locked dependencies, and can obtain Python 3.12 if needed. Initial installation requires access to the Python and package downloads unless they are already cached. The help command should show the `--output-dir` option and exit.

There is no need to activate `.venv` when the client uses its Python executable by absolute path.

### 3. Prepare the target project's configuration

Create your game project and its `.codex` folder if they do not exist:

```powershell
New-Item -ItemType Directory -Force -Path 'C:\Games\KnightGame\.codex' | Out-Null
```

Open `C:\Games\KnightGame\.codex\config.toml` in a text editor. Preserve any existing content and add:

```toml
[mcp_servers.gensprite]
command = 'C:\GenSprite\.venv\Scripts\python.exe'
args = ["-m", "gensprite_mcp", "--output-dir", 'C:\Games\KnightGame\.gensprite']
cwd = 'C:\Games\KnightGame'
enabled = true
startup_timeout_sec = 60
```

Replace **all three paths** with your actual source Python, target asset store, and target project paths. TOML single-quoted strings preserve Windows backslashes. If `[mcp_servers.gensprite]` already exists, update that table instead of adding a duplicate.

Codex uses TOML here, not a JSON `mcpServers` object. Project trust and configuration layers are described in the [official Codex configuration documentation](https://learn.chatgpt.com/docs/config-file/config-basic).

### 4. Reopen Codex and check the connection

Open Codex in `C:\Games\KnightGame`, accept its trust prompt if shown, and ask it to list GenSprite tools. Use the [first-sprite steps](#confirm-the-connection-and-create-your-first-sprite) below to exercise generation and animation.

Source installations depend on the source checkout, `.venv`, and its underlying Python runtime remaining at the configured paths. Moving or deleting those files breaks the connection. If uv's Python lives under `.tools\python`, keep that directory too.

### Source installation on macOS or Linux

Install uv using its official guide, then run `uv sync --locked --python 3.12` in the source checkout. Use the same Codex TOML table with absolute POSIX paths:

```toml
[mcp_servers.gensprite]
command = '/absolute/path/GenSprite/.venv/bin/python'
args = ["-m", "gensprite_mcp", "--output-dir", '/absolute/path/KnightGame/.gensprite']
cwd = '/absolute/path/KnightGame'
enabled = true
startup_timeout_sec = 60
```

The Python source server is separate from the Windows-only Setup application. This checkout's latest local verification was performed on Windows; the CI configuration includes Ubuntu checks.

## Install a Python wheel

Choose this method if you have the built package and want to keep a dedicated Python environment without the source checkout. These steps require Python 3.11 or newer available as `python`.

### 1. Create a dedicated environment

In Windows PowerShell:

```powershell
python --version
$runtimeDir = Join-Path $env:LOCALAPPDATA 'GenSprite-Python'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
python -m venv (Join-Path $runtimeDir '.venv')
$pythonExe = Join-Path $runtimeDir '.venv\Scripts\python.exe'
```

### 2. Install the release file

Replace the wheel path if your release is somewhere else:

```powershell
& $pythonExe -m pip install 'C:\GenSprite\dist\gensprite_mcp-1.2.0-py3-none-any.whl'
& $pythonExe -m pip check
& $pythonExe -m gensprite_mcp --help
$pythonExe
```

`pip check` should report no broken requirements. Installing from a local wheel may still download its dependencies. Use the filename for the release you actually have; this guide does not assume the package has been published to a public registry.

### 3. Configure the client

Copy the real path printed by `$pythonExe`. Follow the source method's project configuration step, replacing `command` with that interpreter path. Keep `args`, `cwd`, and the per-project `.gensprite` path in the same format.

Do not paste `$pythonExe`, `$env:LOCALAPPDATA`, or `%LOCALAPPDATA%` into TOML expecting shell expansion. Use the resolved absolute path. Reopen Codex in the target project and confirm tool discovery.

For macOS or Linux, create a dedicated environment with `python3 -m venv <directory>`, install the wheel with that environment's `bin/python -m pip install <wheel>`, and use its absolute `bin/python` path in the client configuration.

## Confirm the connection and create your first sprite

These are prompts for your connected AI agent. They do not require a demo webpage or game engine.

### 1. Check discovery

> Use GenSprite to inspect its available tools. Confirm the server is connected, and explain where this project's assets will be stored. Do not create any assets yet.

Version 1.2.0 exposes 65 tools. If the client cannot find them, check the project folder, configuration, and trust state before asking it to generate artwork.

### 2. Exercise a built-in sprite and animation

> Use only GenSprite tools. Create the native knight template with create_sprite, keep the master unchanged, then generate its supported idle and attack animations with generate_animation. Use review_asset to inspect the master and animations, validate them, export portable packages, and publish the knight with build_asset_library. Show me the named files, gallery, and frame timing. Keep all outputs in this project's GenSprite store.

The unchanged native knight has deterministic idle and attack animation plans. This is a quick way to check the complete local generation, animation, validation, and export path without requiring optional client sampling.

### 3. Create your own artwork

> Use GenSprite to create a 32 by 32 pixel knight with a consistent palette. Author the pixels or import your own generated PNG, then author distinct idle and attack poses on the same canvas and palette. Review the actual master image before drawing animation poses, refine any issues, then assemble the poses with explicit frame durations. Review the contact sheet and playback where available, validate and export, then label the final master and publish it with build_asset_library. Preserve the original master and return the asset IDs and local file paths.

The connected agent is responsible for the drawing and poses. `create_pixel_art` accepts exact pixel rows and a palette. `generate_game_art` can accept the same drawing. `import_asset` accepts base64 PNG bytes or a PNG data URL; passing a filesystem path as its image argument is not an import.

For custom animation, the agent supplies frame asset IDs or explicit pixel frames. A prose prompt alone needs a client that negotiates MCP sampling. If sampling is unavailable, have the agent provide the artwork directly. GenSprite does not download an AI image model or infer arbitrary motion from a still image on its own.

### 4. Inspect the returned files

A completed animation includes numbered PNG frames, a horizontal PNG strip, a GIF preview, and a manifest describing timing, frame rectangles, pivot, source IDs, and hashes. Export operations return the paths to their generated files and packages. Let the agent report those paths rather than assuming a particular generated asset ID or filename.

Jobs can return before processing finishes. The agent should poll `check_job_status` until the job completes, fails, or is cancelled before using its output.

Automated validation checks technical properties such as pixels, dimensions, palette, alpha, frame order, and timing. `ready_for_export` means those checks passed. Artistic quality and motion readability remain the authoring agent's responsibility; there is no human approval gate in the server.

## Review and browse assets

Version 1.2 adds two tools: `review_asset` and `build_asset_library`. The default authoring guidance now asks the agent to inspect and refine actual images before delivering them, then publish finished assets in a readable library.

**Visual review:** `review_asset` accepts a sprite or animation ID and returns an actual PNG image through MCP, plus factual observations. Sprite boards show native-size context, an enlarged preview, silhouette, and palette. Animation boards show ordered poses with durations. Bounds, edge contact, isolated pixels, palette usage, and placement changes help the agent find issues. These observations are hints: a detached sword effect or deliberate jump is not automatically a defect. The tool does not redraw pixels or assign an artistic score.

The agent should inspect the returned board, revise the artwork where needed, and review again. A contact sheet shows poses; inspect the GIF separately to judge playback when the client supports it. A client without image inspection should disclose that limitation. The MCP supplies feedback and editing tools; craftsmanship still comes from the authoring agent.

**Readable delivery:** ask the agent to give finished sprites concise names with `update_asset_label`, then call `build_asset_library` with the final master sprite IDs. The tool includes their animations and returns the local gallery path. For example:

> Review and refine the final knight and its animations. Name the master Silver Knight, publish it with build_asset_library, and show me the gallery link and named files. Keep intermediate poses out of the published selection.

Typical output:

```text
.gensprite/
  library/
    index.html
    index.json
    silver-knight--<short-id>/
      sprite.png
      preview.png
      asset.json
      attack--<short-animation-id>/
        preview.gif
        spritesheet.png
        manifest.json
        000.png
        ...
```

Open the returned `index.html` directly in a browser. Search by name, inspect crisp thumbnails, open native files, and choose when to play animation previews. No web server or internet connection is needed for the gallery. Animation frames remain beside their manifest so its original relative paths stay valid.

Publication happens once at the end of a batch when the agent calls the tool, not on every intermediate pose save. Older integrations can call it explicitly. Repeated publication keeps previous library entries; changing a label updates the displayed name while preserving its existing folder path.

Each publication accepts 1 to 200 finished master sprites. A library holds up to 1,000 masters, 20,000 managed files, and 256 MiB, with an index up to 8 MiB. If animation discovery reaches its scan limit, publication reports incomplete discovery instead of silently omitting animations.

The library is a derived delivery copy. Use GenSprite's editing tools to revise the canonical asset, then publish the selected result. Editing a copied file does not update the original. GenSprite refuses to replace modified managed files or conflicting destinations; preserve your changes and resolve the reported conflict before republishing. Publication keeps a bounded transaction journal so a failed or interrupted update can restore its previous state without treating its own partial output as a user edit. Canonical ID folders and existing exports remain available, and no existing asset folder is automatically migrated.

To receive this update in an installed project, run the new `dist\GenSprite-Setup.exe`, reconnect that project, and reopen Codex. Updating the source checkout alone does not replace a previously installed executable.

## Connect another project

For a Setup installation, run the same `GenSprite-Setup.exe` again, select the other project's root, and click **Connect to Codex**. Reopen Codex in that project.

Each connected project gets its own `.codex/config.toml` entry and `.gensprite` store. The installed runtime can be shared; assets and history are separate. Repeating Setup for the same project and release is safe and does not reset existing artwork.

For a source or wheel installation, repeat the manual TOML configuration in the second project. Reuse the same absolute Python executable, but change `cwd` and `--output-dir` to the second project's paths.

Run **one GenSprite server process per asset store**. Avoid opening multiple client sessions that start separate GenSprite processes against the same project's `.gensprite` directory at once.

## Files, storage, and backups

Your game source files and GenSprite's asset store are separate. GenSprite keeps generated images, original imports, manifests, revisions, animations, exports, job records, and the organization database under the configured output directory.

For a complete backup:

1. Stop the Codex session using that store so the server is no longer writing.
2. Copy the **entire `.gensprite` directory**, including `catalog.sqlite3` and all subfolders.
3. Keep the project's `.codex/config.toml` separately if you want to preserve its connection settings.
4. To restore, stop the server first and restore the complete store to the configured path.

Copying only exported PNGs preserves those images but loses revision history, job records, and organization data. Configuration backups created by Setup are not backups of your artwork.

You decide whether generated assets belong in version control. Do not delete `.gensprite` as if it were a disposable build cache. Moving to a different Windows account or computer requires reconnecting or updating runtime paths because the installed executable lives in that user's profile.

In the GenSprite source checkout, `.tools\python` may back the active virtual environment, while `.tools\uv` contains the local package tool. Keep these when using that source environment. Browser QA folders, temporary wheel environments, downloaded archives, and Windows build intermediates are not required to run an installed release.

## Update or remove GenSprite

### Update an installed Windows project

1. Back up the project's `.gensprite` store.
2. Obtain the new trusted Setup executable.
3. Close the project's active Codex session.
4. Run Setup, select the project, and connect it again.
5. Reopen Codex and confirm the connection.

Setup installs a versioned runtime and updates that project's configuration. It keeps older runtime versions because other projects may still reference them. Repeat the connection step for each project you want to update. There is no automatic updater.

For source installations, stop the server, update the source, run `uv sync --locked --python 3.12`, and reopen the client. For wheel installations, stop the server and install the new wheel into the same dedicated environment. Back up the asset store before either method.

### Disconnect a project

1. Close its Codex session.
2. Open `<project>\.codex\config.toml`.
3. Remove the `[mcp_servers.gensprite]` table and any nested tables belonging to it, preserving other settings.
4. Reopen Codex.

Keep `.gensprite` to preserve artwork and history. Delete it only when you intentionally want to delete that project's stored assets.

### Remove installed runtime files

After disconnecting every project that uses them, you can remove unused runtime versions under `%LOCALAPPDATA%\GenSprite\versions`. Keep configuration backups if you still need them. There is no separate automatic uninstaller, and disconnecting a project does not delete its assets.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `GenSprite-Setup.exe` is missing | A source checkout may not include built releases. Use source installation or build Setup from the full checkout. |
| Setup reports an invalid project path | Choose an existing writable project root. Drive roots, symlinks, junctions, and other reparse-point paths are rejected. |
| Setup cannot write `.gensprite` | Check permissions. A regular file named `.gensprite` conflicts with the required directory; preserve or rename that file before retrying. |
| Setup cannot parse existing configuration | Fix the TOML error in `.codex/config.toml`. Do not add duplicate `[mcp_servers.gensprite]` tables. Setup refuses malformed or oversized configuration instead of replacing it. |
| Setup reports a concurrent configuration change | Close another editor or process changing the configuration, review the file, and retry. |
| Setup succeeds but Codex shows no GenSprite tools | Reopen Codex in the selected project root. Check its trust state, local MCP settings, and any managed restrictions. |
| The configured executable no longer exists | Reconnect with Setup, or correct the absolute Python path for a source/wheel installation. |
| `No module named gensprite_mcp` | The configuration points to the wrong Python environment, or the package was removed. Reinstall into that environment and use its absolute interpreter path. |
| A manually launched server appears to wait forever | A stdio MCP waits for protocol input from its client. Use `--help` for a terminal check; connect through Codex for normal operation. There is no web page to open. |
| A prompt-only generation call reports sampling is unavailable | Ask the agent to supply pixel rows, a base64 PNG, or frame assets explicitly. Sampling support depends on the client. |
| An animation job has no output yet | Poll `check_job_status`; inspect failure details if it fails. A returned job ID does not mean files are already complete. |
| A job fails after restarting Codex | Interrupted work is marked failed. Inspect the job and submit new work; do not assume a partial file set is a completed animation. |
| Library publishing reports an interrupted or busy publication | Wait for any active publish to finish. If the previous server stopped unexpectedly, close all sessions using that store before following the lock-recovery guidance in the error; preserve any reported user-modified files. |
| A PNG or animation fails validation | Use the returned error to correct canvas, palette, alpha, pose count, or timing. Import limits and explicit pose requirements still apply. |
| An exported file is not visible in a remote client | Output paths refer to this computer. A remote or cloud-only client needs its own supported way to access local files and stdio tools. |

For source/wheel startup diagnosis, run the exact configured Python with `-m gensprite_mcp --help`. For MCP discovery, use the client's server status view and error logs. Avoid running a second server against an already active store while investigating.

## Available workflows and limits

| Workflow | What GenSprite provides |
| --- | --- |
| Sprite authoring and import | Exact rows/palette rendering, native templates, and base64 PNG imports |
| Refinement and revisions | Image edits, background removal, alpha refinement, immutable derived assets, history, and rollback |
| Animation | Explicit frame assembly, per-frame timing, manifests, strips, GIF previews, and native knight motion plans |
| Jobs | Status polling, cancellation, bounded concurrency, durable job records, and interruption detection |
| Characters and tilesets | Character workflows, directional metadata, native tiles, and agent-authored atlases |
| UI kits | Concept selection, sheet generation, component extraction, and final PNG/manifest packages |
| Organization | Projects, collections, labels, metadata, recent assets, and saved private presets |
| Review and browsing | Agent-visible review boards, factual improvement hints, named library copies, and a local searchable gallery |
| Delivery | Portable ZIP exports, integrity hashes, engine descriptors/helpers, and explicit project integration |

Export targets include `generic`, `phaser`, `pixijs`, `flame`, `godot`, `unity`, `libgdx`, and `canvas`. Engine-specific output includes resources such as Godot SpriteFrames and TileSet files where applicable. File validation does not execute a game engine or certify the result in every engine version.

`integrate_asset` returns an integration plan by default. Explicit execution creates a fresh export directory in the selected project and refuses overwrites. `report_integration_error` records an incident locally; it does not send a support message.

MCP resources include `gensprite://assets/{asset_id}/image` and `gensprite://assets/{asset_id}/manifest`. The `sprite_production_workflow` prompt describes the production sequence. Clients can inspect registered tool schemas for the exact arguments supported by the installed version.

Current technical bounds:

- Native canvases: 8 to 256 pixels per side, with 1 to 32 palette colors.
- Sampling-generated canvases: at most 64 by 64; supply larger artwork explicitly.
- Imported PNG data: at most 4 MiB, with soft alpha requiring explicit refinement.
- Animation: 1 to 16 poses; durations of 10 to 10,000 milliseconds in multiples of 10.
- Duplicate poses are rejected unless explicitly permitted through the frame-assembly API.
- Coordinates use a top-left origin with integer rectangles and pivot positions.
- A GIF preview repeats for inspection; the manifest carries the animation's intended loop or one-shot behavior.

Edits produce new asset IDs so the master remains available. Technical checks cover output structure, source provenance, dimensions, palette, alpha, frame order, timing, and file integrity. They do not replace the agent's visual judgment.

## Build a Windows installer

This section is for maintainers building Setup, not users who already have the executable. Use a **Windows x64 machine and a complete source checkout**, including `scripts`, `src`, `pyproject.toml`, and `uv.lock`.

From the checkout root:

```powershell
Set-Location 'C:\GenSprite'
uv sync --locked --group build --python 3.12
uv run --locked --group build python scripts/build_windows.py
```

The first build may download Python packages. The builder packages a console MCP server and a windowed Setup application, checks an actual sprite/animation/export workflow against the packaged server, and exercises the packaged Setup with temporary projects.

Successful output:

```text
dist\GenSprite-Setup.exe
dist\GenSprite-Setup.exe.sha256
```

Build intermediates are placed under `.tools\windows-build`. They can be removed after a successful build; keep the final release files and any Python runtime backing your source environment. The end-user Setup executable does not require those intermediates, the checkout, or a separate Python installation.

The build does not publish the release, sign the executable, install it for every project, or configure a hosted service.

## Developer release checks

Automated release checks are retained in the source project. Demo pages and retained sample output are not required for normal use.

```powershell
uv sync --locked --python 3.12
uv run --locked python scripts/release_check.py
uv build
```

The release check runs the automated Python suite with warnings treated as errors, Ruff, and a real stdio MCP smoke covering discovery, exact agent pixels, animation frames/timing, validation, and ZIP integrity. Smoke assets use a temporary store that is removed on exit. `uv build` creates the wheel and source archive in `dist`; it does not build the Windows installer.

The latest local application release check passed **242 tests**, Ruff, and the production MCP smoke on Windows with Python 3.12. The standalone server and packaged Setup checks also passed. The [CI workflow](.github/workflows/ci.yml) defines Windows and Ubuntu Python 3.11/3.12 checks plus Windows installer packaging; defining those jobs is separate from having run them on a hosted CI service.

The latest local checks did not run Docker, game engines, every MCP client, or a second Windows machine. Those environments require their own checks when they become deployment targets.

| Source location | Purpose |
| --- | --- |
| `src/gensprite_mcp` | MCP server, asset processing, workflows, exports, and Setup implementation |
| `scripts/release_check.py` | Automated release verification using temporary assets |
| `scripts/build_windows.py` | Standalone Windows release builder and package checks |
| `tests` | Automated regression checks retained for releases |
| `examples/mcp-config.json` | Manual stdio example for clients that use JSON `mcpServers` configuration |
| `pyproject.toml` and `uv.lock` | Python package metadata and locked source dependencies |
| `dist` | Locally built distribution files, when present |
