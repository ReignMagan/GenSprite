# Deploying GenSprite MCP

GenSprite runs as a local stdio MCP server on Python 3.11 or newer. An MCP client starts the process and communicates through stdin/stdout; diagnostics go to stderr. There is no HTTP listener, hosted account, provider API key, or GPU requirement in this server.

The connected AI agent supplies the artwork as native-grid pixel rows, base64 PNGs, or animation frame asset IDs. Clients that negotiate MCP sampling can ask their authoring model to supply structured artwork. Sampling is optional: use `create_pixel_art`, pass `drawing={rows,palette}` to `generate_game_art`, import a PNG with `import_asset`, and pass `frame_asset_ids` or pixel `frames` to `animate_game_art` when sampling is unavailable. Sampling and any model charges are controlled by the client.

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
.venv\Scripts\python.exe -m pip install .\dist\gensprite_mcp-1.0.0-py3-none-any.whl
.venv\Scripts\python.exe -m gensprite_mcp --output-dir C:\GenSpriteData
```

On Linux or macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install dist/gensprite_mcp-1.0.0-py3-none-any.whl
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

Core limits are native canvases of 8..256 pixels per side, 1..32 palette colors, binary alpha, PNG inputs up to 4 MiB, and animations of 1..16 frames. Durations are 10..10,000 milliseconds in multiples of 10. Organization lists return at most 200 items; filesystem discovery scans at most 2,000 entries and explicitly marks incomplete totals. Private preset settings are bounded to 64 KiB of JSON. Invalid inputs and tampered source digests fail technical validation.

GenSprite's local processing has no server-side credit meter. Client model subscriptions, token charges, hardware use, and storage still depend on your environment. This package does not use or reproduce SpriteCook's private hosted providers, subscriptions, or billing APIs. Export checks verify file contents, metadata, frame order and timing; game-engine imports and runtime behavior must be checked in the target engine.

## Continuous integration

`.github/workflows/ci.yml` installs locked dependencies and runs the same release check on Ubuntu and Windows with Python 3.11 and 3.12. Each successful job builds and uploads its wheel and source distribution. Docker builds, client-specific sampling, and game-engine execution are separate from that workflow.
