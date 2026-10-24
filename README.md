# GenSprite MCP

GenSprite is a local sprite-production MCP for AI agents. The connected agent designs the artwork; GenSprite preserves its native pixels, refines images, assembles animation, tracks revisions, organizes assets, and builds reusable export packages.

Version 1.0 exposes 63 tools, including the 44 SpriteCook-style workflow names in the [compatibility reference](docs/compatibility.md). It runs over stdio without a hosted account, image-provider API key, or human approval gate. Its local contracts are discoverable through MCP; it is an independent implementation with different provider, billing, URL, and parameter semantics.

## Install and connect

Python 3.11 or newer is required. From this checkout:

```powershell
uv sync --locked
uv run --locked python scripts/release_check.py
uv build
```

For this Windows checkout, [examples/mcp-config.json](examples/mcp-config.json) launches the existing environment directly:

```json
{
  "mcpServers": {
    "gensprite": {
      "command": "C:\\GenSprite\\.venv\\Scripts\\python.exe",
      "args": ["-m", "gensprite_mcp", "--output-dir", "C:\\GenSprite\\assets"]
    }
  }
}
```

Restart the MCP client after adding the entry. For an installed wheel, Linux/macOS, Docker, persistent storage, and CI, see [deployment.md](docs/deployment.md). The server waits for MCP traffic; it has no browser dashboard.

## Author and animate

1. The agent chooses a canvas and palette, then submits `create_pixel_art(rows, palette)` or `import_asset(image, display_name)` with base64 PNG bytes. `generate_game_art` and `generate_character` accept the same artwork and return durable job IDs.
2. Save the returned `asset_id` as the immutable master. Use `edit_sprite`, `refine_sprite`, `remove_background`, or `set_asset_alpha_cutoff` to create derived versions. The original stays available through `get_asset_history` and `rollback_asset`.
3. The agent draws distinct poses on the master's canvas and palette. Call `animate_game_art(asset_id, prompt, frame_asset_ids, durations_ms, loop)` or supply pixel `frames`. `assemble_animation` and `build_spritesheet` accept a `FrameAnimationRequest` directly.
4. Poll `check_job_status(job_id, wait_seconds)` until completed, failed, or cancelled. A completed animation includes numbered PNGs, a horizontal PNG strip, a GIF preview, and a manifest with per-frame timing, rectangles, pivot, source IDs, and hashes.
5. Run `validate_sprite` or `validate_animation`, then `export_asset(asset_id, target)`. Targets are `generic`, `phaser`, `pixijs`, `flame`, `godot`, `unity`, `libgdx`, and `canvas`.

For example, an agent can submit a small native drawing to `generate_game_art`:

```json
{
  "prompt": "A deliberate green marker",
  "width": 8,
  "height": 8,
  "drawing": {
    "rows": ["........", "........", "........", "...XX...", "...XX...", "........", "........", "........"],
    "palette": {"X": "#00FF00"}
  },
  "wait_seconds": 5
}
```

`.` is transparent; each palette key is one ASCII symbol. The server renders these exact pixels without resizing. Structured drawing is intended for agents that can author pixels. An agent with image-generation tools can instead import its PNG output and motion poses. Supplying only a prose prompt requires a client that negotiates MCP sampling; unsupported clients receive an actionable error asking for explicit artwork. No separate local image server is needed for the explicit-artwork workflow.

The optional sampling path requests structured artwork from the connected client's model, with only the request and an owned reference image. Sampling support and model charges belong to the client. Arbitrary motion comes from supplied or sampled poses. Built-in heart and knight templates remain available through `create_sprite`; only an unchanged native knight has deterministic idle/attack motion plans.

## Production workflows

| Work | Tools and behavior |
|---|---|
| Jobs | `check_job_status`, `cancel_job`, `list_active_jobs`; durable state, bounded concurrency, real outputs, interruption detection |
| Characters | `list_character_workflows`, `generate_character`, `generate_character_animations`, `check_character_animation_run`; source identity and platformer/topdown/isometric direction passed to the agent |
| Tiles | `list_tileset_options`, `generate_tileset`; exact native tiles or agent-drawn atlases, including row-major 4x4/15-piece layouts |
| UI kits | Create kit, generate concepts, select concept, generate sheets, extract named rectangles or alpha components, finalize PNGs/manifest, or cancel |
| Organization | Projects, collections, labels, recent assets, metadata, animation outputs, saved private presets, and restart persistence in SQLite |
| Imports | Base64 PNG import or expiring local upload slots; original source bytes retained for explicit alpha refinement |
| Delivery | Portable ZIPs, hashes, engine descriptors/helpers, Godot SpriteFrames/TileSet resources, project detection, integration plan and explicit execution, integrity verification |
| Diagnostics | `report_integration_error` records a bounded incident locally; nothing is sent externally |

MCP also exposes `gensprite://assets/{asset_id}/image`, `gensprite://assets/{asset_id}/manifest`, and the `sprite_production_workflow` prompt. These resources let a local client read an asset without interpreting its file URL.

## Accuracy and data rules

Automated checks enforce exact dimensions, RGBA PNG encoding, visible content, binary alpha, palette membership, frame count/order/timing, source provenance, and PNG/strip/GIF pixel integrity. Successful files report `technical_status: "passed"`, `status: "ready_for_export"`, `art_review_status: "agent_responsibility"`, and `approval_source: "automated_technical_checks"`. No human confirmation is needed to export. The authoring agent owns silhouette, visual consistency, and motion quality; technical checks do not certify those judgments.

- Native canvases: 8..256 pixels per side; 1..32 colors. Sampling-generated canvases are limited to 64x64; larger artwork must be supplied explicitly.
- Imported PNGs: at most 4 MiB. Soft alpha must be explicitly refined; the source bytes remain unchanged.
- Animations: 1..16 poses, 10..10,000 ms per pose in multiples of 10. Duplicate poses are rejected unless `allow_duplicate_frames` is explicitly set through `assemble_animation`.
- Top-left pixel origin; integer rectangles and pivot coordinates. One-shot/loop behavior is carried in the manifest; GIF previews repeat for inspection.
- Edits create new asset IDs. Operations validate generated IDs, bounded data, palette/canvas constraints, path containment, source digests, and link/reparse-point exclusions.
- One server process per persistent output directory. A cancelled worker retains its concurrency slot until processing ends; already-written files can remain. Interrupted work is reported as failed after restart.
- `integrate_asset` returns a plan by default. `execute=true` creates a fresh export directory in the selected project and refuses overwrites. Verification checks file integrity; it does not run an engine.

Keep the entire output directory when backing up assets, including `catalog.sqlite3`, original PNGs, manifests, jobs, and exports. No secrets or external image-provider credentials are required by GenSprite.

## Release verification

```powershell
.venv\Scripts\python.exe scripts\release_check.py
```

This runs the automated suite with warnings as errors, Ruff, and a real stdio MCP workflow covering tool discovery, exact agent pixels, frame animation, validation, ZIP integrity, and timing. All smoke assets use a temporary store that is removed on exit. The suite also exercises imports, sampling, revisions, jobs/cancellation, organization, UI kits, tilesets, exports, and safe integration. Demo pages, demo scripts, and retained sample outputs have been removed.

The [CI workflow](.github/workflows/ci.yml) runs the release check on Windows and Ubuntu with Python 3.11/3.12 and builds wheel/source archives. Docker and engine-runtime execution are separate checks. See the [compatibility reference](docs/compatibility.md) for the exact boundary between this local implementation and SpriteCook's hosted service.
