# GenSprite production refactor

The user requests repository-wide improvements to performance and pixel-art quality,
plus a working local OpenCode MCP connection. They selected artwork supplied by their
AI client. GenSprite remains a local production toolkit with no bundled image model.

## Design

Preserve existing tools, IDs, storage contracts, immutable revisions, exports, and
Codex setup. Refactor the shared processing paths instead of replacing functioning
subsystems. Existing baseline: 242 passing tests; installed OpenCode: 1.18.31.

Add a dungeon pixel-art brief for original Soul Knight-inspired assets: compact
silhouettes, deliberate dark outlines, small palettes, coherent light, readable poses,
native pixels and nearest-neighbor previews. Return prompts and a motion checklist
for the connected AI client; technical validation never certifies aesthetic quality.

Add explicit preparation of AI PNGs up to 4096px per side and 4 MiB. Accept base64 or
an explicitly supplied absolute local PNG path. Preserve source bytes and digest;
fit the full image proportionally inside an 8..256px canvas with explicit padding,
nearest-neighbor resampling, binary alpha, optional border-matte removal and a fixed
palette or bounded color reduction without dithering. Preserve placement rather than
trimming each pose independently. Native import remains pixel-exact and strict.

Remove duplicate generation imports/saves and avoid drawing the same input twice.
Optimize exact RGB palette matching and connected-component slicing without changing
their results. Keep integrity checks rather than caching externally editable files.
Reject invalid animation timing and poses before any pose files are persisted.

Extend verified, atomic project setup with Codex/OpenCode selection. Preserve unrelated
settings, backups, size limits, link checks and concurrent-edit detection. Handle strict
OpenCode JSON and reject JSONC edits with an actionable manual configuration instruction
instead of discarding comments. Support the installed v1 layout; document v2 separately.
Ship a project configuration and verify discovery with the installed OpenCode CLI.

## Validation

Test source preservation, exact nearest pixels, aspect/padding, alpha recovery, matte
connectivity, bounded sources, invalid poses without partial writes, setup preservation
and idempotency. Run all tests, Ruff, the real stdio smoke, an isolated OpenCode connection,
and repeatable processing benchmarks. Inspect a generated preparation review board.
No new runtime dependencies, direct image provider, automatic artistic-quality score,
or unrelated hosting/UI subsystem.
