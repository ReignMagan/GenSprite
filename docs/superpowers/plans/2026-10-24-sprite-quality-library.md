# Sprite Quality and Library Implementation Plan

> **For agentic workers:** Use the approved design and test-first implementation. Independent modules may run in parallel; root owns integration and release checks.

**Goal:** Make artwork review actionable and delivered sprites easy to browse.
**Architecture:** Preserve AssetStore; add review.py and library.py using existing validation/catalog APIs. Register two tools in server.py, return MCP image content, and publish static local gallery copies explicitly at batch completion.
**Tech Stack:** Python 3.11+, Pillow, MCP, existing SQLite catalog, plain HTML/CSS/JS.
**Spec:** docs/superpowers/specs/2026-10-24-sprite-quality-library-design.md

## Global Constraints
- Existing IDs and canonical storage remain unchanged; no external user asset folder inspected.
- No new dependency or model backend; no forced art approval or aesthetic score.
- Safe Windows names, path containment, no links/junctions, no overwriting changed user files.
- Local release 1.2.0; no public push/upload.

## Review Focus
- Existing library files modified by users must cause an actionable conflict.
- Invalid or hostile library metadata must never escape the managed root or inject HTML.
- Animations must preserve native bytes, order and timing; isolated parts are hints, not failures.
- Repeated batches retain previous entries; renamed labels preserve stable folder links.
- MCP clients receive real image blocks; unsupported sampling still allows explicit pixels.

### Task 1: Visual review (review.py, tests/test_review.py)
- [x] Write and run failing tests for sprite bounds/isolated pixels and animation review boards, integrity rejection, and bounded previews.
- [x] Implement review_asset(store, asset_id) -> tuple[dict, bytes] where bytes are a PNG board, and reusable preview helper if needed. Accept a_ or n_ IDs. No mutations.
- [x] Run focused tests and Ruff; report concrete results.

### Task 2: Library (library.py, tests/test_library.py)
- [x] Write and run failing tests for named PNG/GIF copies, idempotency, retention, label changes, hostile names, modified destination refusal, path links, and index limits.
- [x] Implement build_asset_library(store, asset_ids: list[str]) -> dict with gallery_path, index_path, assets and counts. Library owns validated index schema and hashes. No reliance on review module.
- [x] Create local searchable gallery with keyboard/reduced-motion behavior and explicit animation playback. Add focused tests and inspect relative links.

### Task 3: MCP integration and authoring (server.py, production.py, tests/test_mcp.py, scripts/release_check.py)
- [x] Add a failing real MCP integration test for both new tools and image content.
- [x] Register review_asset returning ImageContent plus TextContent; register library publication with bounded selection.
- [x] Strengthen server/prompt/sampling guidance and replace misleading one-pixel example. Require inspect/refine before delivery, then named library publication.
- [x] Extend production smoke for packaged server review/library calls; verify existing callers.

### Task 4: Release (README, deployment docs, pyproject, uv.lock, dist)
- [x] Update version 1.2.0, docs, tool counts and supported workflow.
- [x] Run release_check.py, inspect browser gallery, and request final independent code review.
- [x] Fix meaningful findings with regressions; rerun affected checks.
- [x] Build wheel/source/Windows setup; verify checksums and embedded version. Remove temporary retained QA assets/build intermediates safely.

## Ledger
- User approved design and requested immediate implementation without further design questions.
- Parallel work uses separate owned module/test files; root handles shared integration.

- Task 1: complete. 12 visual-review tests pass, including a RED/GREEN one-frame heading-clipping regression. Independent review found no substantive visual-workflow bugs.
- Task 3: complete. Real MCP integration plus extended release smoke pass (2 tests). Existing MCP/installer/Setup coverage passes (23 tests).
- Browser: local Chrome at 1280px and 390px passed 11 interaction assertions each; screenshot inspected. All image/download links resolve.
- Ruling: keep numbered animation frames beside their copied manifest, because its original paths are relative filenames; no duplicate frames/ subdirectory.
- Final review: interrupted-publication rollback and Python 3.11 reparse-point checks require regressions and fixes before packaging. Implementer is adding a bounded durable transaction journal, conservative recovery, and lstat-based checks.

- Task 2: complete. 31 library regressions pass; all reported interruption/concurrent-edit/junction failures have observed RED/GREEN coverage. Independent reviewer replayed their exact failing scenarios and found no remaining important issue.
- Full source release check: 242 tests passed with warnings as errors in 64.19 seconds, Ruff clean, and real stdio artwork/animation/export/review/library smoke passed.
- Release artifacts: building 1.2.0 wheel, source archive and standalone Windows Setup next.

- Release complete: wheel/sdist verified; fresh offline wheel install outside checkout passed 65-tool discovery and the full real MCP smoke. Metadata README matches after standard newline normalization; sdist README bytes match exactly.
- Standalone server passed real MCP artwork, animation, export, review image and named-library calls. Packaged GUI self-check passed for version 1.2.0 / 65 tools, preserving configuration, backups, repeated setup, separate projects and temporary-store cleanup.
- Final Setup is Windows x64, 37.3 MiB, SHA-256 verified. Build intermediates and temporary browser/gallery assets removed. Active Python/uv retained and post-cleanup discovery still reports 65 tools.
- All implementation tasks complete. No external user asset folder was inspected or modified; no GitHub push/public upload performed.
