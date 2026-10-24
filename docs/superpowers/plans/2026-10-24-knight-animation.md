# GenSprite Knight and Animation Implementation Plan

**Goal:** Generate the user's knight, idle and attack assets using our local MCP, with no SpriteCook or game-engine integration.

**Spec:** `GenSprite_MCP_Project_Plan.md`, constrained to the user's immediate sprite request. Broader pipeline work remains future work.

**Architecture:** Keep immutable still assets and existing heart behavior. Add a native-grid knight drawing function, fixed deliberate pose plans (4 idle, 6 attack), and an animation package with PNG frames, strip, GIF and JSON. Expose generation and validation as two additional MCP tools. Leave art-review status pending.

**Scope:** `models.py`, `assets.py`, `knight.py`, `animation.py`, `server.py`, unit/integration tests, a knight MCP example, README. Existing profile palette/size locks and path confinement apply. No external API, provider account, model download or game engine.

## Tasks

- [x] Native-grid knight: `draw_knight(width, height, palette, motion='idle', frame=0) -> Image`. Test exact size, binary alpha, palette lock, planted feet, unclipped and distinct frames. Drawing delegated to its own file to keep changes independent.
- [x] Input and manifest contract: accept `template='knight'`, reject knight canvases below32, retain heart compatibility. Animation inputs take a generated master ID, `idle|attack`, and a positive duration in multiples of10ms. Test trust boundaries.
- [x] Animation store: immutable generated IDs, validate master before generation, write4/6 frames, strip coordinates, timing and digest metadata, GIF preview. Validate frame/strip/preview bytes, dimensions, palette, alpha and digest; fail if source changed. Test tampering and unsupported heart animation.
- [x] MCP: add `generate_animation` and `validate_animation`; run full tests and real stdio knight creation plus both animation calls. Save actual outputs to `assets/knight-demo`.
- [x] Inspect native master and all frames at nearest-neighbor zoom. Update docs with supported capabilities and pending human-review limits; independent review and final tests.

## Progress

- Baseline verification:34 tests passed, Ruff clean, real heart MCP smoke passed.
- User correction: do not use SpriteCook; no SpriteCook generation submitted.
- User priority: generate sprites first; do not spend this task on game engines.

- Completed:58 tests passed, Ruff clean, real stdio knight + idle + attack generation and validation succeeded. Native and magnified pose sheets inspected.
- Independent read-only review found no Critical, Important or Minor issues; 48 additional in-memory GIF shape/palette/motion combinations retained exact frame pixels and counts.
- Package:0.2.0 wheel and source distribution built. Final ZIP includes master, both animation packages and review previews.
- Boundary: broader AI generation, editing/approval/version workflows and engines remain roadmap items; this completed milestone is the user's prioritized local sprite generation request.
