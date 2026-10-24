# GenSprite Agent Production MCP Implementation Plan

> Execute task-by-task using the existing TDD and verification workflow. Independent modules may be implemented in parallel; root integrates and runs the release checks.

**Goal:** Replace the restricted demo with an agent-driven sprite-production MCP using SpriteCook-style asset/job/animation/organization/export workflows.

**Architecture:** The connected AI agent supplies native-grid artwork or PNG frames; optional negotiated MCP sampling obtains the same structured artwork from a supporting client. GenSprite owns bounded drawing/import, immutable revisions, refinement, frame assembly, metadata, validation, jobs, organization and exports. No SpriteCook service calls, API keys, private provider models, billing, or human approval gate. Automated technical readiness is explicit; artistic authorship belongs to the agent.

**Spec:** Original GenSprite plan plus latest user corrections: no human verification, remove demo pages/sample outputs, retain automated release checks, operate like SpriteCook, artwork originates with the user's AI agent.

## Shared interfaces

- Existing `AssetStore(root)`, `_path`, `_manifest`, `inspect_sprite`, `validate_sprite` remain available.
- Root adds `AssetStore.save_image(image: Image.Image, description: str, palette: list[str] | None = None, template: str = 'agent', asset_type: str = 'character', parent_asset_id: str | None = None, metadata: dict | None = None) -> dict`.
- Saved image results retain `asset_id`, `png_path`, `manifest_path`, `validation`, and `status`, now `ready_for_export` after technical checks. Manifest adds immutable parent/reference/provenance metadata and agent/imported templates. Legacy manifests remain readable.
- Native canvas 8..256, palette1..32, RGBA PNG, binary alpha; source data and processing inputs are bounded. No arbitrary URL fetching, shell execution, or writes outside the store.
- Modules export `register_*_tools(server, store)` and own only their files. Tests use temporary stores, not retained samples.

## Tasks

- [x] Root core: agent pixel drawings, generic immutable images, automated readiness, durable jobs/status/cancellation, frame-source animation assembly, sampling adapter and compatible generation wrappers. Tests cover invalid agent output, source fidelity, job persistence and real stdio calls.
- [x] Image operations: bounded base64 PNG import; explicit alpha/palette refinement; non-destructive crop/recolor/flip/pixel edits; source/history/rollback; connected-alpha slicing. Register familiar import/refinement/metadata tools. Test real pixel behavior and safe bounds.
- [x] Organization: SQLite-backed projects, collections, labels, recent assets, animation discovery and private presets with validated IDs, transactional assignments and restart persistence. No fake hosted accounts/credit balances.
- [x] Export: validated generic PNG/JSON ZIP plus Phaser/Pixi/Flame/Godot/Unity/LibGDX import contracts, export manifests and safe optional project integration (plan then explicit execution). Test file contents and pixel/timing mappings; document engine-runtime verification limits.
- [x] Workflow parity: character preparation/animation runs, tileset options and native grid atlas assembly, UI-kit concept selection/slicing/finalization using agent-provided artwork, tool/resource discovery and actionable unsupported capability errors. No advertised tool may silently fake an output.
- [x] Release: replace demo-based checks with self-contained release coverage, package/stdio smoke, CI and deployment docs; remove only confirmed demo pages/scripts/sample outputs; build and inspect wheel; independent final review.

## Review focus

- Canvas/palette/alpha limits, malformed base64, decompression bombs and oversized JSON.
- Symlinks/traversal, immutable version ancestry and export/integration overwrite protection.
- Sampling unavailable or malformed responses; no automatic approval prompts or provider calls.
- Cancelled/interrupted jobs and process restarts must never claim successful outputs.
- Compatibility names must describe actual local semantics; billing/private-model behavior is outside this standalone agent-driven implementation.

## Progress

- User explicitly chose removing demos/sample outputs while keeping automated release checks.
- User clarified that artwork generation/craftsmanship comes from the connected AI agent. No separate image-model installation is required for the core workflow.
- Final source release gate: 175 tests passed with warnings treated as errors; Ruff passed; real stdio discovery/artwork/animation/validation/ZIP smoke passed.
- Final independent review findings were reproduced and fixed: invisible RGB in GIF comparisons, accepted prompt/persistence limits, terminal cancellation stability, and compatibility documentation. Added regressions pass; PNG/strip fidelity remains exact.
- Built version 1.0.0 wheel and source archive. Inspected both: no tests, demos, sample assets, tools, or caches. Every wheel module matches reviewed source.
- Installed the wheel and declared runtime dependencies in a fresh isolated environment; verified actual installed module paths and CLI; final installed-wheel real MCP smoke passed and removed temporary outputs.
- Removed demo HTML/templates/scripts, obsolete demo-only checks, generated sample folders/images/ZIPs, and old 0.1/0.2 distributions. The persistent assets directory is empty. Automated release checks remain in source only.
- Deployment docs, client JSON, Docker recipe, and Windows/Ubuntu Python 3.11/3.12 CI are provided. Local execution was Windows/Python 3.12.15; Docker, hosted CI, Linux, and game-engine runtimes were not executed.
- Published compatibility contract distinguishes the 44 familiar workflow names from private hosted generation/billing and explains local artwork, upload, preview, and export semantics.
