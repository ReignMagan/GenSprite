# GenSprite MCP — Project Plan

**Project:** Universal Pixel-Art Sprite Generation MCP Server  
**Status:** Agent-production release candidate; see README for verified scope  
**Primary language:** Python 3.11+  
**Target:** Any 2D game engine or framework that can consume image assets, including Flutter/Flame, Godot, Unity, LibGDX, Phaser, PixiJS, HTML5 Canvas, GameMaker, and custom engines.

**Current implementation (2026-10-24):** GenSprite 1.0 implements 63 local stdio MCP tools: 44 SpriteCook-style workflow names plus native drawing, validation, immutable edits/history/rollback, arbitrary agent pose animation, jobs, projects/collections/presets, tilesets, UI kits, exports, and opt-in file integration. The connected AI agent supplies visual content directly or through optional client sampling. See [README.md](README.md), [compatibility.md](docs/compatibility.md), and [deployment.md](docs/deployment.md) for current contracts and limits.

**User-directed policy update:** Human verification/approval gates are removed. Passing automated technical validation yields `ready_for_export`; artwork craftsmanship remains the authoring agent's responsibility. No software claim of aesthetic perfection is made. Demo pages and generated sample outputs are removed, while automated release checks remain in the source checkout and are excluded from deployment archives. This policy supersedes the original human-checkpoint proposals below.

**Scope of the implemented release:** Exact native pixels, palette/alpha constraints, timing, source integrity, version lineage and file integration are automated. SpriteCook's private hosted generation models, accounts, billing, cloud uploads, HD/video generation, semantic terrain/UI inference and engine-runtime execution are outside this standalone local implementation. The longer-term suggestions in this original plan are design history; they do not change the published tool contracts.

## 1. Vision

Build an engine-agnostic Model Context Protocol (MCP) server that lets AI coding agents create, revise, animate, validate, organize, and export **actual pixel-art game assets**. The system must prioritize precise dimensions, crisp pixels, consistent palettes, stable character identity, repeatable animations, and portable output—not just images that resemble pixel art.

### Success criteria

- Agents can request an asset using structured specifications.
- Every exported frame has exact requested dimensions and valid alpha transparency.
- Pixel-art rules (allowed colors, nearest-neighbor scaling, no unintended smoothing) are checked automatically.
- Animation frames have defined timing, anchors, and consistent metadata.
- Users can approve a master character reference and generate variants without losing the approved source.
- The same asset can be exported to generic PNG/JSON and multiple engine-specific formats.
- All generation and editing operations are versioned and reversible.
- Failures are reported honestly; technical checks must not be presented as proof of artistic quality.

## 2. Scope

### In scope

- Characters, enemies, NPCs, props, items, equipment, UI icons, effects, terrain tiles, and tilesets.
- 8×8, 16×16, 32×32, 64×64, and custom canvas sizes.
- Transparent PNG frames; fixed and custom color palettes.
- Idle, walk, run, attack, hurt, and death frame animations.
- Sprite strips, grid sheets, packed atlases, and portable JSON metadata.
- Engine adapters and optional project-aware asset integration.

### Deferred

- 3D meshes, skeletal animation, advanced isometric perspective, full game-scene generation, proprietary native project files for every engine, and automatic guarantees of aesthetically perfect animation.

## 3. Recommended tools

| Layer | Tool | Role | Priority |
|---|---|---|---|
| MCP server | Official MCP Python SDK / FastMCP | Register tools, resources, prompts, and transports | Required |
| Runtime | Python 3.11+ | Server and processing logic | Required |
| Image manipulation | Pillow | PNG/RGBA operations, frames, sheets | Required |
| Arrays | NumPy | Pixel-level operations and palette checks | Recommended |
| Validation | Pydantic | Typed requests, metadata, schema validation | Required |
| AI artwork | Connected agent pixel/PNG input; optional client sampling | Original artwork and reference-guided revisions | Implemented |
| Tests | pytest | Unit and integration tests | Required |
| Linting | Ruff | Code quality | Recommended |
| Types | mypy or pyright | Static type checking | Recommended |
| Image analysis | OpenCV | Optional shape/alignment comparisons | Later |
| Pixel editor | Aseprite or LibreSprite | Human review and editing | Optional |
| Asset registry | SQLite | Profiles, versions, generation history | Later |
| Packaging | uv or pip + pyproject.toml | Dependencies and reproducible setup | Recommended |
| Version control | Git + GitHub | Collaboration, CI, releases | Recommended |

Useful documentation: [MCP](https://modelcontextprotocol.io/), [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), [Pillow](https://pillow.readthedocs.io/), [Aseprite CLI](https://www.aseprite.org/docs/cli/), [Flame](https://docs.flame-engine.org/), [Godot](https://docs.godotengine.org/), [Phaser](https://docs.phaser.io/).

**Practical starting stack:** Python + FastMCP + Pillow + NumPy + Pydantic + pytest + one image backend. Avoid adding OpenCV, a database, and editor automation until needed.

## 4. Architecture

```text
AI Coding Agent (Codex / Claude Code / Cursor / others)
                    |
               MCP client
                    |
           GenSprite MCP Server
                    |
   +----------------+-----------------+
   |                |                 |
Spec & Project   Generation       Asset Registry
  Profiles         Backends       and Versioning
   |                |                 |
   +----------------+-----------------+
                    |
           Pixel Processing
      (palette, alpha, alignment)
                    |
        Animation and Sheet Builder
                    |
       Validation and Review Gates
                    |
       Universal Asset Representation
       (frames + metadata + sources)
                    |
             Export Adapters
     +--------------+--------------+
     |              |              |
  Generic       Flame/Phaser    Godot/Unity/
  PNG/JSON        atlases        LibGDX/etc.
```

**Design rule:** Generate and validate once, then export through adapters. An adapter may produce PNG/JSON, a texture atlas, or an engine-specific descriptor. Never claim universal support for every proprietary engine format.

## 5. Universal asset schema

Store a project art profile and each asset's immutable ID. Example:

```json
{
  "schema_version": "1.0",
  "asset_id": "slime_green_001",
  "type": "character",
  "style": "pixel_art",
  "canvas": {"width": 32, "height": 32},
  "palette": ["#2D6A4F", "#40916C", "#52B788", "#95D5B2"],
  "transparent": true,
  "reference_asset": "references/slime_master.png",
  "pivot": {"x": 16, "y": 30},
  "animations": {
    "idle": {
      "frames": ["idle/000.png", "idle/001.png", "idle/002.png", "idle/003.png"],
      "durations_ms": [125, 125, 125, 125],
      "loop": true
    }
  }
}
```

Use a consistent pixel-coordinate convention, documented pivot behavior, schema versioning, and relative paths. Include optional collision shapes, tags, layer definitions, directional variants, source provenance, and license metadata later.

## 6. Pixel-art accuracy requirements

### Hard checks (automatable)

1. Exact canvas width and height.
2. RGBA PNG encoding and correct transparency handling.
3. Pixels use only approved palette colors when palette lock is enabled.
4. No unintended interpolation during resize; use nearest-neighbor for pixel-art scaling.
5. Correct frame count and valid animation duration values.
6. Consistent pivot/anchor coordinates and export metadata.
7. Sprite-sheet coordinates are in bounds and do not overlap unexpectedly.
8. Tiles intended to repeat seamlessly match across opposite edges where applicable.
9. File paths remain inside approved output directories.
10. Asset versions and source references remain traceable.

### Soft checks (review or model-assisted)

- Character identity, anatomy, face, outfit, and silhouette consistency.
- Natural-looking motion and readable poses.
- Pixel clusters, outline quality, and shading coherence.
- Appropriate perspective and visual consistency with the project.

**Important:** Resizing an AI-generated image to 32×32 does not automatically create good 32×32 pixel art. Use reference-guided generation, controlled palette conversion, manual or model-assisted cleanup, and an approval checkpoint. Visual checks should report confidence/observations rather than pretending to prove quality.

### Mandatory rule: authentic pixel art, not AI-style imitation (NON-NEGOTIABLE)

**GenSprite MUST produce deliberate, production-quality pixel art that could plausibly have been drawn and cleaned up by an experienced pixel artist.** An image that merely *looks pixelated* or has an AI-generated pixel-art aesthetic is **not acceptable** as a finished sprite. AI may assist with ideation or propose candidate shapes, but every final exported pixel must belong to an intentional, coherent pixel grid and satisfy the project's art-direction rules.

**Reject or require correction for:**

- Blurry or interpolated edges, antialiasing, semitransparent halos, and mixed-resolution pixels unless explicitly authorized for a specific effect.
- Fake pixel texture: random checkerboards, noisy dithering, excessive one-pixel speckles, stray pixels, and arbitrary detail without readable form.
- Broken pixel clusters, jagged or inconsistent outlines, banding, pillow shading, incoherent highlights, and inconsistent light direction.
- Anatomical mistakes, accidental extra or missing features, inconsistent proportions, shifting facial features, or changing costume details across frames.
- Palette drift, unapproved colors, inconsistent pixel density, perspective mismatch, and broken silhouettes at native resolution.
- Animation jitter, wandering feet or pivots, shape morphing without animation intent, duplicated frames presented as distinct poses, and discontinuous motion.
- Upscaled or downscaled AI artwork presented as finished pixel art without pixel-level cleanup and review.

**Required production procedure:**

1. Lock the native sprite resolution, pixel grid, perspective, palette, outline rules, and light direction before final drawing.
2. Build or approve a master sprite with a readable silhouette and purposeful pixel clusters; use it as the immutable reference for related assets and animation.
3. Draw, edit, or reconstruct at native pixel resolution using grid-aware operations. Nearest-neighbor scaling is allowed for previews, **not** as evidence that a source image is authentic pixel art.
4. Inspect at **native 1× scale** and nearest-neighbor magnification. Run deterministic checks for dimensions, palette, alpha, and frame layout; use visual review for craftsmanship and design consistency.
5. For animations, compare frames against the approved master and a pose plan; verify pivots, feature identity, silhouette changes, and playback coherence.
6. If a check fails, return actionable findings, preserve the previous approved version, and request revision. **Never silently accept, auto-approve, or label a failing asset as `game_ready`.**
7. Run automated technical checks without a human approval gate. The connected agent owns art-direction review; technical tests do not prove artistic quality.

**Acceptance policy:** Successful technical validation yields `ready_for_export`, `art_review_status: agent_responsibility`, and `approval_source: automated_technical_checks`. Failed checks yield `failed` with findings. No human gate or `game_ready` aesthetic guarantee is used. Preserve immutable source/version manifests.

**Agent instruction (copy verbatim into the MCP server's tool guidance):**

> Generate authentic, intentionally constructed pixel art—not an AI-styled, pixelated illustration. Respect the exact native pixel grid, approved palette, silhouette, outlines, lighting, perspective, and master-character reference. Eliminate AI artifacts and visually inconsistent pixels. Automated technical checks determine ready_for_export; no human approval gate is required. Artistic craftsmanship belongs to the authoring agent and must never be claimed as proven by technical checks. Report uncertainty honestly.

## 7. Generation strategies

### A. Procedural

Pillow drawing operations for deterministic shapes, simple sprites, icons, tiles, and effects. Best for exact pixel placement.

### B. AI-based

Use a replaceable backend for character concepts and reference-guided edits. The backend interface should accept prompt, reference images, dimensions, palette, and seed when supported; capabilities vary by model.

### C. Hybrid (default)

1. Agent submits structured request.
2. Validate constraints and retrieve project style profile.
3. Generate a master image or draw a procedural base.
4. Convert/refine to target pixel grid and palette; inspect results.
5. Preserve the agent-selected master design as an immutable reference when character identity matters.
6. Generate or derive frames using approved reference and motion plan.
7. Align pivots, validate each frame, and produce previews.
8. Export universal package and target-specific formats.
9. Return paths, metadata, warnings, and validation report.

Do not automatically retry indefinitely; cap regeneration attempts and preserve earlier versions.

## 8. MCP tool API plan

| Tool | Inputs | Outputs | Phase |
|---|---|---|---|
| `create_project_profile` | project, palette, perspective, sizes | profile ID | 1 |
| `get_project_profile` | profile ID | rules | 1 |
| `create_sprite` | description, dimensions, palette, reference | asset ID + PNG | 1–2 |
| `inspect_sprite` | asset ID/path | dimensions, colors, metadata | 1 |
| `validate_sprite` | asset ID, rules | structured pass/fail/warnings | 1 |
| `edit_sprite` | asset ID, edits, optional mask | new asset version | 2 |
| `get_asset_metadata` | asset ID/version | immutable master and source provenance; no approval gate | Implemented |
| `generate_animation` | asset ID, motion, frames, timing | frame sequence | 3 |
| `validate_animation` | animation ID | consistency report | 3 |
| `build_spritesheet` | frame IDs, layout | sheet PNG + frame rectangles | 3 |
| `preview_animation` | animation ID | GIF/APNG preview | 3 |
| `detect_engine` | project path | suggested engine + evidence | 4 |
| `export_asset` | asset ID, target adapter | files + manifest | 4 |
| `integrate_asset` | project path, export manifest | proposed changes, then approved edits | 5 |
| `verify_integration` | project path, target | checks and diagnostics | 5 |

MCP **resources** can expose style profiles, asset manifests, and generation history. MCP **prompts** can provide reusable workflows (e.g., generate a 4-direction character). Tools perform actions. Keep long-running generation operations cancellable and provide status or progress where supported.

## 9. Engine-agnostic export strategy

| Target | Initial output |
|---|---|
| Generic | Individual PNG frames + sprite sheet + JSON manifest |
| Flutter / Flame | PNG sprite sheet with frame dimensions/timing metadata and documented loading example |
| Godot | PNG sprite sheet or individual frames + JSON metadata; optional Godot-specific resources later |
| Unity | PNG sprite sheet/atlas + JSON metadata; Unity import helper later |
| LibGDX | PNG sprite sheet; TexturePacker-style atlas support later |
| Phaser | PNG sheet or texture atlas + compatible JSON |
| PixiJS | PNG atlas + supported atlas JSON |
| HTML5 Canvas | PNG + JSON rectangles/timing |
| GameMaker | Individual PNGs or strips |
| Other/custom | Generic PNG/JSON contract, extensible adapter interface |

Adapters must document coordinate origins, frame ordering, padding/extrusion, pivots, animation timing, scaling/filtering, and import instructions. Validate against real engine loaders, not just JSON syntax. Do not write into a user's game project without explicit approval.

## 10. Proposed repository structure

```text
gensprite-mcp/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/gensprite_mcp/
│   ├── server.py
│   ├── config.py
│   ├── tools/
│   │   ├── sprites.py
│   │   ├── animation.py
│   │   ├── validation.py
│   │   └── exports.py
│   ├── schemas/
│   │   ├── assets.py
│   │   ├── animations.py
│   │   └── projects.py
│   ├── generation/
│   │   ├── base.py
│   │   ├── procedural.py
│   │   └── ai_provider.py
│   ├── processing/
│   │   ├── palette.py
│   │   ├── alpha.py
│   │   ├── alignment.py
│   │   └── sheets.py
│   ├── validation/
│   │   ├── technical.py
│   │   └── visual.py
│   ├── registry/
│   │   └── assets.py
│   └── exporters/
│       ├── base.py
│       ├── generic.py
│       ├── flame.py
│       ├── godot.py
│       ├── unity.py
│       ├── libgdx.py
│       └── phaser.py
├── assets/
│   ├── references/
│   ├── generated/
│   └── exports/
├── examples/
│   ├── generic/
│   └── flame/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── docs/
    ├── architecture.md
    ├── asset-schema.md
    └── exporter-contract.md
```

## 11. Development roadmap

### Phase 1 — MCP foundation and deterministic sprites

**Deliverables:** working local MCP server, project profile, procedural 16×16/32×32 sprite creation, PNG export, dimensions/transparency/palette validation, tests.

**Acceptance test:** Agent requests a 32×32 transparent heart icon; server returns a PNG with exact dimensions, correct palette, and a structured validation report.

### Phase 2 — AI generation and reference consistency

**Deliverables:** pluggable AI provider, approved master references, editing/version history, palette conversion, agent-owned art direction with automated technical readiness.

**Acceptance test:** Agent generates a character, revises its color while preserving the approved original, and can roll back.

### Phase 3 — Animation pipeline

**Deliverables:** idle/walk frame creation, pivots, durations, GIF preview, sprite-sheet builder, animation validation.

**Acceptance test:** Agent requests four 32×32 idle frames; server exports a 128×32 strip, source frames, and correct timing metadata. Visual consistency receives separate review.

### Phase 4 — Universal export adapters

**Deliverables:** generic PNG/JSON, Flame, Godot, Phaser, Unity, and LibGDX adapters; sample loader projects.

**Acceptance test:** The same character animation loads correctly in at least two different engines, with consistent timing and alignment.

### Phase 5 — Agent integration and hardening

**Deliverables:** safe project inspection, optional integration, sandboxed paths, size/time limits, deterministic tests, CI, usage documentation.

**Acceptance test:** An agent can request an asset, review it, export it, and integrate it into a sample project without damaging existing files.

### Phase 6 — Advanced features (optional)

- Directional sprite variants (4/8 directions).
- Tileset autotiling and seamless-edge validation.
- Palette swaps and skin variations.
- Layer-based animation and controlled pose transforms.
- Batch asset-pack generation and dependency tracking.
- Pixel-cluster quality metrics and stronger visual review.
- Local model support and generation queues.

## 12. MVP checklist

- [x] Initialize Python package and Git repository.
- [x] Implement FastMCP server over local stdio transport.
- [x] Define Pydantic sprite request/response models.
- [x] Implement a procedural sprite generator using Pillow.
- [x] Add RGBA, dimension, palette, and alpha validation.
- [x] Add `create_sprite`, `inspect_sprite`, and `validate_sprite` tools.
- [x] Write unit tests for invalid dimensions and palette constraints.
- [x] Export PNG and universal JSON manifest.
- [ ] Connect an AI coding agent (SDK stdio client calls are tested; host registration remains manual).
- [ ] Add an AI backend only after deterministic operations work.

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| AI output looks like pixel art but has poor pixel clusters | Keep source images; use controlled processing and visual review |
| Character changes between animation frames | Approved master reference, locked palette, pose planning, human review |
| Animation jitter | Consistent canvas/pivots, frame alignment checks |
| Model API cost or downtime | Pluggable backend, procedural fallback, caching, quotas |
| Export format mismatch | Adapter-specific fixture tests in real engines |
| Agent overwrites game assets | Sandboxed paths, dry-run plan, versioning, explicit approval |
| Oversized or malicious inputs | File size/pixel count limits, safe path resolution, image decoding limits |
| Excessive scope | Deliver generic PNG/JSON MVP before engine adapters |

## 14. Quality assurance plan

- **Unit tests:** palette enforcement, RGBA conversion, dimensions, alpha, pivot validation, frame packing.
- **Property tests:** random valid dimensions and frame counts never produce out-of-bounds metadata.
- **Golden-image tests:** procedural outputs remain pixel-identical across refactors where expected.
- **Integration tests:** MCP tool discovery/calls, generation backend mocks, asset registry, export adapters.
- **Engine smoke tests:** sample Flame and Phaser/Godot projects load exported sprites and animate correctly.
- **Human review:** silhouette readability, palette coherence, character consistency, and motion quality.

Track measurable metrics: technical validation pass rate, export-load success rate, average generation latency, generation cost per accepted asset, human acceptance rate, and number of regeneration attempts.

## 15. Suggested first demonstration

**Green Slime Character**

- Master design: 32×32, transparent, fixed four-color green palette plus optional outline colors.
- Animations: idle (4 frames) and walk (6 frames).
- Outputs: individual PNG frames, sheets, animation manifest, GIF preview, and validation report.
- Export targets: generic PNG/JSON first, then Flame and Phaser.
- Agent checkpoint: preserve the selected base sprite ID before generating animation; no human gate.

This is small enough to test but covers the core technical challenges: pixel accuracy, consistency, animation, validation, and portability.

## 16. Definition of done

The initial project is ready for practical use when an AI agent can reliably request a constrained pixel-art sprite, receive correct PNG files and metadata, inspect validation results, regenerate or edit a version, and export the approved asset to at least two real game engines without manual format conversion.

**Guiding principle:** GenSprite should be a reliable pixel-art *production pipeline*, not merely a text-to-image wrapper. Authentic pixel-art craftsmanship is a release requirement, not an optional visual preference.
