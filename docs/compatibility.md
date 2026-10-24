# SpriteCook-style workflow compatibility

GenSprite 1.0 is an independent local, agent-authored sprite-production MCP. It implements the following 44 familiar workflow names and adds 19 native drawing, validation, revision, and export tools. The release smoke requires every name below to be registered. Tools carry their actual input schemas through MCP discovery; the table describes local behavior, not byte-for-byte compatibility with SpriteCook's hosted API.

| Workflow | Familiar tools | Local behavior |
|---|---|---|
| Artwork | `generate_game_art`, `generate_character`, `list_generation_models`, `get_credit_balance` | Explicit agent drawings/PNG or negotiated client sampling; durable jobs; source identity and perspective metadata; actual connected-agent capability, unmetered local processing |
| Animation | `animate_game_art`, `list_character_workflows`, `generate_character_animations`, `check_character_animation_run`, `list_animation_outputs` | Agent pose assets/pixels or sampled poses; exact native canvas/palette; timing, source IDs, strip/GIF validation; per-character motion runs |
| Job control | `check_job_status`, `cancel_job`, `list_active_jobs` | Persistent queued/running/completed/failed/cancelled state; at most eight active/draining workers; interrupted work fails after restart |
| Import/refinement | `import_asset`, `create_asset_upload`, `finalize_asset_upload`, `remove_background`, `set_asset_alpha_cutoff`, `auto_slice_asset` | Bounded PNG bytes/local upload slots; original-source retention; border-connected background removal; explicit alpha cutoff; alpha-connected component slices |
| Asset catalog | `get_asset_metadata`, `list_recent_assets`, `update_asset_label` | Real immutable manifests, file URLs, validation, labels, and bounded discovery |
| Projects/collections | `create_project`, `list_projects`, `create_collection`, `list_collections`, `assign_assets_to_project`, `assign_assets_to_collection` | Local SQLite catalog with transactional assignments and persistent IDs |
| Presets | `save_private_preset`, `list_presets`, `get_preset_settings` | Bounded saved settings and reference asset IDs; agent retrieves settings and passes them to generation explicitly |
| Tiles | `list_tileset_options`, `generate_tileset` | Agent-drawn atlas or exact supplied tiles; row-major grid and 4x4/15-piece layout; no automatic terrain-mask inference |
| UI kits | `create_ui_kit`, `get_ui_kit`, `list_ui_kits`, `generate_ui_kit_concepts`, `select_ui_kit_concept`, `generate_ui_kit_component_sheets`, `extract_ui_kit_components`, `finalize_ui_kit`, `cancel_ui_kit` | Persistent concept/sheet jobs; owned concept selection; explicit named rectangles/nine-patch border metadata or alpha slicing; validated component PNGs and manifest |
| Engine handoff | `export_godot_character_package`, `export_godot_tileset_package`, `report_integration_error` | Real Godot resources from validated animation/tile metadata; local-only incident records |

Additional GenSprite tools: `create_project_profile`, `get_project_profile`, `create_sprite`, `inspect_sprite`, `validate_sprite`, `generate_animation`, `validate_animation`, `assemble_animation`, `build_spritesheet`, `preview_animation`, `create_pixel_art`, `edit_sprite`, `refine_sprite`, `get_asset_history`, `rollback_asset`, `export_asset`, `detect_engine`, `integrate_asset`, and `verify_integration`.

## Generation contract

The calling agent authors visual content. It can submit `drawing={rows,palette}` or base64 PNG `image` to `generate_game_art`, and pose IDs or pixel frames to `animate_game_art`. A prose-only call uses optional negotiated MCP client sampling. If unavailable, the server requests explicit artwork rather than returning fabricated art, silently switching providers, or demanding an image API key. For stills, supplied artwork is one variation; multiple variations require independently authored drawings or sampling.

Reference IDs are preserved and passed to sampling. Explicit artwork is already the agent's final interpretation of its request; GenSprite validates pixels, constraints, and provenance rather than deciding whether a supplied picture depicts the prompt. Imported images keep original bytes. Revisions, supplied animation poses, and export packages preserve source links and hashes.

`generate_character_animations` returns a durable run ID. Its `animation_ids` are local motion names from `list_character_workflows`, not hosted provider IDs. `custom_animations` accepts `{id,prompt,output_frames?}` with distinct lowercase motion IDs. Supply per-motion `frame_asset_ids` or `frames` dictionaries when client sampling is unavailable. Poll each job or `check_character_animation_run` until terminal state. Unsupported/malformed input fails visibly.

## Deliberate differences from the hosted service

- No SpriteCook account, proprietary model, private API, subscription, or billing is reproduced. `get_credit_balance` reports `credits: null` with `mode: local_unmetered`. Model use belongs to the MCP client.
- URLs are local `file:` URIs, not signed hosted downloads. `create_asset_upload` returns an expiring local payload path, not an HTTP PUT endpoint. Direct base64 import is available for clients that cannot write the server filesystem.
- Native assets are 8..256 pixels per side, 1..32 colors with binary alpha. HD illustration generation is outside this pixel-art contract. Explicit alpha refinement preserves original soft-alpha bytes for later cutoff changes.
- Animation output formats are `gif` and `spritesheet`; both are generated along with numbered PNGs and JSON. Animated WebP/video outputs are not implemented. Loop/one-shot intent is in the manifest; GIF previews repeat for inspection.
- A tileset's 15-piece layout describes cell order. The authoring agent supplies the correct visual connectivity; the server does not infer dual-grid terrain semantics or certify tile-edge seamlessness.
- UI extraction uses supplied rectangle names, or placeholder labels for alpha components. Semantic UI recognition, color themes, and art direction belong to the agent.
- `report_integration_error` persists a local incident and never contacts SpriteCook or another service.
- Automated `ready_for_export` means technical validation passed. Art craftsmanship and coherent poses belong to the authoring agent; no human approval gate is required.
- Export verification checks actual bytes, hashes, metadata, frame timing and rectangles. Engine loading/runtime execution is not performed by this MCP. `integrate_asset` provides a plan unless `execute=true` is explicitly supplied, and refuses overwrites.

## Export formats

| Target | Package contract |
|---|---|
| Generic / Canvas | Original PNGs, numbered frames, strip, GIF preview, portable `import.json`, source manifests and hashes; Canvas loading example |
| Phaser / PixiJS | Portable frame rectangles and per-frame PNG loading/animation examples with explicit timing |
| Flame | Native strip plus loader contract/example and frame durations |
| Godot | `.tres` SpriteFrames for character animation, or TileSet resources for tiles with explicit grid metadata |
| Unity | PNGs and a C# import/loading helper with portable timing/pivot metadata |
| LibGDX | Numbered PNGs, portable frame metadata and a Java loading example |

Packages contain `export.json`, `import.json`, loading guidance, source assets, and an integrity-checked ZIP. No engine is required to generate/export. Use the source repository's automated release checks before packaging; engine-runtime validation is a separate deployment concern.
