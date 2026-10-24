# Knight HTML Tester Implementation Plan

**Goal:** Use the existing knight in one self-contained HTML page to inspect and verify playback.

**Design:** Embed validated PNG strips, individual frames and manifests. Canvas renders at native32x32 with integer nearest-neighbor CSS zoom. Controls cover idle, attack once, pause/play, frame stepping, speed, zoom and guides. An actual-size preview and automatic pixel/timing/layout/feet checks support inspection. This is a local test artifact, with no hosting or external dependencies at runtime.

- [x] Write builder tests first; observe missing implementation. Build validated data into a static HTML template with safe JSON embedding.
- [x] Implement playback from exported per-frame timing, including idle looping and one-shot attack returning to idle. Add self-checks for pixel equality, palettes, alpha, anchored feet and timing boundaries.
- [x] Test real browser controls, rendering, keyboard, all frames, speed and small viewport; capture a screenshot. Run the complete Python suite and build the final standalone file.

Scope: examples/build_knight_tester.py, examples/knight_tester.html (template), tests/test_html_tester.py, browser test, README. Final page: assets/knight-demo/knight-tester.html.

Browser tool initialization failed; use an isolated headless installed browser for automated QA. No user browser profile is involved.

Verification: standalone builder test passed after the expected missing-file failure. Headless Chrome passed9 test groups, including all10 frame pixels, timing, real playback, controls, keyboard, zoom, mobile layout, and zero browser errors/network dependencies. Screenshot inspected. Independent review: no findings.
Timing ruling: sample real rendering after the next requestAnimationFrame refresh; exact mathematical timing boundaries are separately asserted.

Loading-failure fix: the example URL had exposed the unbuilt template. Renamed source to examples/knight_tester.template.html, made examples/knight_tester.html the generated/default playable file, and moved JSON parsing inside the startup error handler. Added a runnable-example regression test. Verified60 Python tests, cleanRuff, and10 browser checks each on the user's exact Live Server URL and the offline example. Tests visit the template using the same protocol as the player to respect browser navigation restrictions.
