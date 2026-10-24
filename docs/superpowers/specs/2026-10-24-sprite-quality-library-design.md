# GenSprite: visual review and readable asset library

Status: implemented and verified in local release 1.2.0; approved by the user on 2026-10-24.

## Intent and user decisions

Improve future sprite-generation workflows and make delivered artwork easy to identify in the filesystem. The connected AI agent remains the artist. GenSprite supplies better authoring guidance, visual feedback, technical diagnostics, and organized delivery.

The user selected a readable library and gallery while preserving internal storage. They explicitly declined inspection or migration of the external .gensprite folder shown in their screenshot. Work targets this source project and its next local release. No external asset folder is modified.

## Approaches considered

1. Selected: maintain a human-readable delivery library alongside immutable ID-based storage. Reuse existing asset labels, descriptions, ancestry, and animation manifests. This adds convenient copies/previews while preserving all existing IDs, references, and APIs.
2. Rejected: rename canonical generated and animation folders. This would require changes to path resolution, discovery, manifests, integrations, and existing stores, without improving the art itself.

## Scope

Two new MCP tools, shared visual-review helpers, stronger server/tool/prompt guidance, documentation, focused regression coverage, and a new local 1.2.0 release. Keep Python/Pillow and existing MCP facilities; no new model service, framework, or mandatory dependency.

### 1. Agent-visible review

Add `review_asset` accepting one existing sprite or animation ID. Validate the stored source before inspecting it. Return actual PNG image content through MCP so a vision-capable agent can see the result without relying on a filesystem URL.

For sprites, provide a bounded review board with a readable nearest-neighbor enlargement, a silhouette, and the palette, alongside dimensions and native-resolution context. For animations, provide an ordered contact sheet with frame numbers and durations, plus the stored GIF path for playback. Contact sheets alone do not demonstrate playback quality; the response must state that distinction.

Return actionable, deterministic observations: visible bounds and canvas occupancy, edge contact that may indicate clipping, isolated visible pixels/components, palette usage, and frame-to-frame bounds/placement changes. Describe these as review hints, not aesthetic scores or mandatory failures. Effects, particles, weapons, and intentional asymmetry must remain valid. Never delete pixels or alter alignment automatically in this tool.

The output explains what the agent should examine: silhouette readability, consistent lighting and color clusters, anatomy and equipment continuity, stable contact points, and motion timing. Do not claim that technical validity proves artistic quality.

### 2. Better authoring workflow

Replace vague quality exhortations and the one-visible-pixel tool example with useful authoring guidance. Have the agent establish the subject, target size, perspective, palette, lighting, and reference identity before drawing. Favor clear silhouettes and deliberate clusters over scattered detail.

The default production workflow becomes: author master -> review the actual master image -> revise where needed -> plan motion key poses and timing -> assemble -> review animation contact sheet and playback where available -> validate/export -> publish to the readable library.

For motion, describe anticipation, action/contact, recovery, weight shifts, and deliberate holds where appropriate. Retain existing supported frame/timing constraints and duplicate-frame semantics. Encourage variable durations rather than treating every pose as equally timed.

Apply consistent guidance to the server instructions, production prompt, relevant tool docstrings, and optional sampling requests. Explicit artwork remains supported without sampling. The MCP cannot guarantee an agent follows guidance or gains a new image-generation capability; do not claim it can independently redraw arbitrary subjects without an authoring model.

### 3. Named asset library and gallery

Add `build_asset_library` taking an explicit bounded selection of finished sprite IDs (1..200). Use catalog labels first, then concise descriptions, then a safe fallback name. Include each selected sprite's validated animations. Do not publish every intermediate pose as a standalone gallery card.

Write under the configured store's `library` directory. Example layout:

```text
.gensprite/
  library/
    index.html
    index.json
    knight--<short-id>/
      sprite.png
      preview.png
      asset.json
      idle--<short-animation-id>/
        preview.gif
        spritesheet.png
        manifest.json
        frames/000.png
      attack--<short-animation-id>/
        ...
  generated/       # existing canonical data, unchanged
  animations/      # existing canonical data, unchanged
  exports/         # existing exports, unchanged
```

Names are filesystem-safe, length-bounded, and collision-resistant on Windows, including reserved device names, case-insensitivity, Unicode, separators, and duplicate labels. Extend a shortened ID if a collision occurs. IDs remain explicit in metadata.

The library is a derived delivery copy, not the editable master. Preserve source pixels and animation timing exactly; enlarged review previews are clearly separate from native sprite files. Editing library copies does not revise canonical assets.

The self-contained local HTML gallery works by opening index.html directly. It uses relative local paths, no external assets or HTTP server, escaped user text, pixelated thumbnails, names, dimensions, and links to native files. Provide a simple search and per-asset animation previews. Accessibility includes labelled controls, visible keyboard focus, and reduced-motion handling; animation playback is user-controlled.

Repeated publishing is safe and updates the selected entries without discarding previously published assets. Existing entries are read from a bounded, validated library index; do not scan arbitrary files or silently truncate. Define explicit size/item limits and return actionable capacity errors. Labels may change the displayed name while the existing managed folder remains stable to avoid breaking links.

Only write recognized generated library files. If a managed destination has been manually changed, or an unknown file occupies a required destination, refuse replacement and return a clear conflict. Use hashes/managed metadata and atomic index replacement; stage and validate new output before exposing it in the index. Reject symlinks/junctions and paths escaping the store. No automatic deletion or migration of original data.

Publication runs once at the end of an agent's generation/refinement batch through this tool. It does not rebuild the gallery on each intermediate frame save. The workflow tells the agent to publish finished assets and return the named paths and gallery link. Existing callers of generation tools continue to work; they may call the new publication tool explicitly.

## Compatibility and release

Keep canonical ID formats, file paths, immutable revision history, existing exports, and validation contracts intact. Update tool-count expectations only where necessary; do not hard-code a new count in runtime UI that already discovers it.

Document the new workflow and library ownership rules in README and deployment documentation. Keep README free of comparison branding. Explain how existing installations receive the update by rerunning the new local Setup executable for each project. Build the wheel, source archive, and Windows installer only after release checks pass. This request does not authorize a new GitHub push or public release upload.

## Verification

- Real MCP calls return image content for sprite and animation review, with bounded dimensions and source integrity enforced.
- Tiny artifacts, clipped bounds, intentional detached parts, and shifted animation frames produce appropriate factual hints without destructive edits or aesthetic pass/fail claims.
- Library copies decode identically to canonical sprite/animation outputs; durations, frame order, and source IDs are preserved.
- Repeated publishing, duplicate names, label changes, existing library entries, unsafe names, hostile HTML metadata, corrupt indexes, modified destination files, and symlink/junction paths have focused regression coverage.
- A temporary end-to-end workflow authors distinct poses, reviews them, animates, publishes, and verifies the gallery and relative links. No retained demo data is added to the project.
- Run the existing automated release check and standalone packaged-server/Setup checks. Inspect the generated temporary gallery's layout and interactions in a browser if browser tooling is available.

## Decisions left to implementation

Exact module names, review-board dimensions within a bounded output budget, conservative warning thresholds, gallery styling, staging layout, and safe capacity limits are builder choices. Reuse current validators and test fixtures. Avoid introducing a generic asset-management framework or an automatic model retry loop.

## Success criteria

A capable connected agent can see what it created, obtain useful improvement hints, revise it, and deliver identifiable files with playable previews. A user can browse names and images without opening opaque asset-ID folders. Existing storage and tools still work. Artistic improvement depends on the authoring agent and is not represented as a guaranteed numerical score.
