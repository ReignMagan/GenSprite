"""A reusable art contract for client-generated dungeon sprites and animation poses."""

from typing import Any

from .image_ops import _palette
from .models import Canvas, Size

ART_DIRECTION = (
    "Act as a deliberate pixel artist. For Soul Knight-inspired dungeon art, use original "
    "characters with compact chibi silhouettes, an oversized readable head, short articulated "
    "limbs, recognizable equipment and a clean one-native-pixel dark outline. Prefer 12-16 "
    "coherent colors, 2-3 discrete shades per material, upper-left lighting and connected "
    "color clusters. Establish subject, native size, perspective and palette before drawing. "
    "Readability at actual size comes first. Avoid soft gradients, antialiasing, noisy texture, "
    "pillow shading, stray pixels and muddy near-identical colors. Use transparent backgrounds. "
    "Preserve reference proportions, equipment, colors and facing across revisions. "
    "For motion, plan anticipation, action/contact and recovery as appropriate; show weight "
    "shifts and articulated limbs instead of merely translating the entire sprite. Keep "
    "ground contact and a stable pivot unless the action requires displacement. "
    "Choose deliberate frame holds and fast actions. Inspect actual pixels at native size "
    "and nearest-neighbor enlargement before delivery. Technical validity is not an art score."
)


def sprite_art_brief(
    description: str, width: Size = 32, height: Size = 32,
    perspective: str = "topdown", palette: list[str] | None = None,
) -> dict[str, Any]:
    """Build a concrete image prompt and pose contract for the connected AI client."""
    canvas = Canvas(width=width, height=height)
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 4000:
        raise ValueError("description must contain 1..4000 characters")
    if perspective not in ("topdown", "platformer", "isometric", "front"):
        raise ValueError("perspective must be topdown, platformer, isometric or front")
    palette = None if palette is None else _palette(palette)
    return {
        "canvas": canvas.model_dump(), "perspective": perspective, "palette": palette,
        "image_prompt": (
            f"Create {description.strip()}. Native canvas {width}x{height} pixels, "
            f"{perspective} view. {ART_DIRECTION} "
            f"Palette: {', '.join(palette) if palette else 'choose 12-16 coherent colors'}. "
            "One complete character, no text, no scene, no contact sheet. Keep clear margins "
            "around equipment and feet. If the image tool requires a larger canvas, use a "
            "uniform integer enlargement of this native pixel grid, with no interpolation."
        ),
        "negative_prompt": (
            "blur, antialiasing, smooth vector edges, gradients, photorealism, 3D render, "
            "uneven pixel sizes, text, watermark, scenery, clipped weapons, stray pixels"
        ),
        "animation_guidance": (
            "Inspect and refine the master visually first. Author distinct poses from that master; "
            "lock canvas framing, palette, facing, equipment and ground pivot. Plan idle "
            "breathing, walk foot contacts/passing poses, and attack anticipation/contact/" 
            "recovery. Express holds through per-frame durations in multiples of 10 ms, "
            "not duplicate frames. Review ordered poses and GIF playback for jitter and loops."
        ),
        "workflow": [
            "Generate the master with the AI client's image tool using image_prompt.",
            "prepare_sprite for a large AI PNG; import_asset for exact native pixels.",
            "review_asset, inspect actual pixels and refine the master before creating poses.",
            "Prepare consistently framed pose images with the same settings and locked palette.",
            "animate_game_art with frame_asset_ids and durations_ms, then review_asset.",
            "export_asset and build_asset_library for finished masters and animations.",
        ],
    }
