# GenSprite production refactor implementation plan

**Goal:** Make client-authored artwork practical to prepare and animate locally, improve
shared processing, and connect OpenCode without breaking the existing workflows.

**Architecture:** Extend current image, production and installer modules. Keep native
import strict; expose image preparation separately. Reuse Pillow, Pydantic and current
asset validation and revision storage.

**Spec:** ../specs/2026-10-29-production-refactor-design.md

**Constraints:** Python >=3.11; no new runtime dependencies; 4 MiB source PNG limit;
8..256 native canvas; <=32 colors; immutable sources and explicit processing.

## Tasks

- [x] Add failing preparation and style-brief tests in tests/test_preparation.py and
  tests/test_art_direction.py. Exercise a real large PNG, native pixel placement,
  source digest/recovery, bounded input and invalid settings before writes.
- [x] Implement bounded decoding in image_ops.py, preparation.py and art_direction.py;
  register both tools in server.py. Run the new tests and existing image/sampling tests.
- [x] Add regression tests for one persisted generation asset and invalid animation
  inputs leaving no pose assets. Refactor production.py to prepare pixels once and
  validate all timing/poses before writing. Optimize palette lookup and slice traversal;
  compare exact results with existing fixtures and measured baseline.
- [x] Add OpenCode preservation/idempotency/error tests in test_installer.py; extend
  prepare_config/connect_project with an explicit client and reuse atomic write checks.
  Add a setup client selector and GUI coverage. Verify the installed v1 config shape.
- [x] Update README, compatibility/deployment docs, examples, release smoke and project
  opencode.json. Run installed OpenCode discovery, complete test suite with warnings as
  errors, Ruff, and real stdio workflow. Inspect a preparation review image and record
  benchmark evidence. Review the final diff for compatibility and data-loss risks.

## Verification evidence

- Final release run: 282 passed, one GUI test skipped; all four GUI tests passed in a
  separate run. Warnings were errors; Ruff and full stdio release smoke passed.
- OpenCode 1.18.31 reports GenSprite connected without path-schema warnings.
- Integer-upscaled 1024px source recovered identical native 32px pixels; review board inspected.
- Same-process baseline comparison: palette matching 3.49x, sprite validation 12.14x faster.
- Independent review findings fixed with regressions: transparent-pose preflight,
  source write before manifest commit, v1 server named `servers`, and v2 preferences.
- Windows server and installer built successfully; hidden setup self-check passed with
  67 tools, both client configs, backups, repeat setup, independent stores and cleanup.
- Wheel/source distribution built and inspected: current source included, local caches
  and assets excluded, OpenCode configuration and processing benchmark included.
