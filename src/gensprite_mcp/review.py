"""Bounded visual evidence for an authoring agent; review never edits the source."""

import hashlib
import io
import math
import re
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .assets import AssetStore
from .models import AnimationManifest

BACKGROUND = "#101820"
FOREGROUND = "#E6EDF3"


def _load(path: Path, digest: str) -> Image.Image:
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Review source exceeds the 4 MiB limit")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Review source integrity changed during inspection")
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGBA")


def _metrics(image: Image.Image) -> dict:
    width, height = image.size
    pixels = list(image.get_flattened_data())
    visible = {(i % width, i // width) for i, pixel in enumerate(pixels) if pixel[3]}
    bounds = image.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("Review requires visible source pixels")
    left, top, right, bottom = bounds
    remaining = set(visible)
    component_sizes = []
    isolated = []
    while remaining:
        seed = remaining.pop()
        pending, size = [seed], 0
        while pending:
            x, y = pending.pop()
            size += 1
            for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
                neighbor = (x + dx, y + dy)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    pending.append(neighbor)
        component_sizes.append(size)
        if size == 1:
            isolated.append(list(seed))
    isolated.sort()
    usage = Counter("#%02X%02X%02X" % pixel[:3] for pixel in pixels if pixel[3])
    return {
        "bounds": {"x": left, "y": top, "width": right - left, "height": bottom - top},
        "visible_pixels": len(visible),
        "canvas_occupancy": round(len(visible) / (width * height), 6),
        "edge_contact": [
            name
            for name, touches in (
                ("top", top == 0),
                ("right", right == width),
                ("bottom", bottom == height),
                ("left", left == 0),
            )
            if touches
        ],
        "component_count": len(component_sizes),
        "largest_component_pixels": max(component_sizes),
        "component_connectivity": 8,
        "isolated_pixel_count": len(isolated),
        "isolated_pixel_positions": isolated[:32],
        "isolated_pixel_positions_truncated": len(isolated) > 32,
        "palette_usage": dict(sorted(usage.items())),
        "ground_y": bottom - 1,
    }


def _observations(metrics: dict) -> list[str]:
    observations = []
    if metrics["edge_contact"]:
        observations.append(
            "Visible pixels touch the "
            + ", ".join(metrics["edge_contact"])
            + " canvas edges. Inspect for clipping; edge contact may be intentional."
        )
    if metrics["isolated_pixel_count"]:
        observations.append(
            f"{metrics['isolated_pixel_count']} isolated pixels have no visible 8-connected "
            "neighbors. Inspect for stray pixels; particles and highlights may be intentional."
        )
    if metrics["component_count"] > 1:
        observations.append(
            f"{metrics['component_count']} disconnected visible components. Check equipment "
            "and anatomy continuity; detached effects may be intentional."
        )
    if metrics["canvas_occupancy"] < 0.1:
        observations.append(
            "Visible pixels occupy less than 10% of the canvas. Check readability at native "
            "size; small effects or deliberately padded animation canvases may be intentional."
        )
    return observations


def _text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int = 14) -> None:
    draw.text(xy, text, fill=FOREGROUND, font=ImageFont.load_default(size=size))


def _panel(board: Image.Image, image: Image.Image, x: int, y: int, scale: int) -> None:
    draw = ImageDraw.Draw(board)
    for row in range(0, 256, 16):
        for column in range(0, 256, 16):
            color = "#263442" if (row // 16 + column // 16) % 2 else "#1C2834"
            draw.rectangle((x + column, y + row, x + column + 15, y + row + 15), fill=color)
    enlarged = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    board.alpha_composite(
        enlarged, (x + (256 - enlarged.width) // 2, y + (256 - enlarged.height) // 2)
    )


def _sprite_board(image: Image.Image, palette: list[str]) -> bytes:
    board = Image.new("RGBA", (848, 466), BACKGROUND)
    draw = ImageDraw.Draw(board)
    _text(draw, (16, 12), f"Sprite review | native {image.width} x {image.height}px", 18)
    scale = max(1, min(8, 256 // max(image.size)))
    silhouette = Image.new("RGBA", image.size, FOREGROUND)
    silhouette.putalpha(image.getchannel("A"))
    for x, title, view, zoom in (
        (16, "Native pixels (1x)", image, 1),
        (296, f"Pixel enlargement ({scale}x)", image, scale),
        (576, "Silhouette", silhouette, scale),
    ):
        _text(draw, (x, 46), title)
        _panel(board, view, x, 70, zoom)
    _text(draw, (16, 342), "Locked palette | compare value separation and consistent shading")
    for index, color in enumerate(palette):
        x, y = 16 + index % 16 * 51, 370 + index // 16 * 42
        draw.rectangle((x, y, x + 40, y + 18), fill=color)
        _text(draw, (x, y + 21), color, 9)
    _text(draw, (16, 453), "Review hints are observations, not an artistic quality score.", 10)
    return _png(board)


def _animation_board(images: list[Image.Image], durations: list[int]) -> bytes:
    columns = min(4, len(images))
    rows = math.ceil(len(images) / columns)
    board = Image.new("RGBA", (max(480, columns * 276 + 16), rows * 294 + 72), BACKGROUND)
    draw = ImageDraw.Draw(board)
    _text(draw, (16, 12), "Animation review | ordered contact sheet", 17)
    _text(draw, (16, 38), "Inspect the GIF separately to judge motion and timing.", 12)
    for index, (image, duration) in enumerate(zip(images, durations, strict=True)):
        x, y = 16 + index % columns * 276, 66 + index // columns * 294
        _text(draw, (x, y), f"Frame {index + 1:02d} | {duration} ms")
        scale = max(1, min(8, 256 // max(image.size)))
        _panel(board, image, x, y + 22, scale)
    return _png(board)


def _png(board: Image.Image) -> bytes:
    output = io.BytesIO()
    board.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def review_asset(store: AssetStore, asset_id: str) -> tuple[dict, bytes]:
    """Return factual geometry and a bounded PNG board for an immutable sprite or animation.

    Detached components and clipping hints are not errors. A contact sheet shows poses,
    not playback; the agent still judges silhouette, lighting, identity, and motion quality.
    """
    if not isinstance(asset_id, str) or not re.fullmatch(r"[an]_[0-9a-f]{32}", asset_id):
        raise ValueError("Review requires a generated a_ sprite ID or n_ animation ID")
    report = {
        "asset_id": asset_id,
        "art_review_status": "agent_responsibility",
        "review_checklist": [
            "Check native-size silhouette readability and intentional pixel clusters.",
            "Check consistent lighting, palette ramps, anatomy, and equipment identity.",
            "Revise observed problems, then review the revised asset before delivery.",
        ],
    }
    if asset_id.startswith("a_"):
        validation = store.validate_sprite(asset_id)
        if validation["errors"]:
            raise ValueError(f"Sprite validation failed: {validation['errors']}")
        manifest = store._manifest(asset_id)
        image = _load(store._path("generated", asset_id, "sprite.png"), manifest.source_sha256)
        metrics = _metrics(image)
        report.update(
            kind="sprite",
            canvas=manifest.canvas.model_dump(),
            palette=manifest.palette,
            validation=validation,
            metrics=metrics,
            observations=_observations(metrics),
            limitations="Geometry hints do not certify artistic quality. Review the actual image.",
        )
        return report, _sprite_board(image, manifest.palette)

    validation = store.validate_animation(asset_id)
    if validation["errors"]:
        raise ValueError(f"Animation validation failed: {validation['errors']}")
    manifest = store._read(store._path("animations", asset_id, "manifest.json"), AnimationManifest)
    images, frames, observations = [], [], []
    previous = None
    for index, frame in enumerate(manifest.frames):
        image = _load(store._path("animations", asset_id, frame.file), frame.source_sha256)
        metrics = _metrics(image)
        delta = {
            key: metrics["bounds"][key] - (previous or metrics)["bounds"][key]
            for key in ("x", "y", "width", "height")
        }
        frames.append(
            {
                "frame": index + 1,
                "duration_ms": frame.duration_ms,
                "metrics": metrics,
                "bounds_delta": delta,
            }
        )
        observations.extend(f"Frame {index + 1}: {hint}" for hint in _observations(metrics))
        if previous and any(delta.values()):
            observations.append(
                f"Frame {index + 1}: visible bounds changed by {delta} from the previous pose. "
                "Check planted feet and unwanted jitter; movement may be intentional."
            )
        previous = metrics
        images.append(image)
    report["review_checklist"].append(
        "Check anticipation, action/contact, recovery, intentional holds, foot contact, "
        "and loop continuity in playback; changing bounds alone does not prove jitter."
    )
    report.update(
        kind="animation",
        canvas=manifest.canvas.model_dump(),
        palette=manifest.palette,
        validation=validation,
        frames=frames,
        observations=observations,
        duration_ms=sum(frame.duration_ms for frame in manifest.frames),
        loop=manifest.loop,
        preview_path=str(store._path("animations", asset_id, manifest.preview)),
        limitations="A contact sheet shows ordered poses, not playback. Open the GIF to review "
        "motion and timing; technical checks do not certify artistic quality.",
    )
    return report, _animation_board(images, [frame.duration_ms for frame in manifest.frames])
