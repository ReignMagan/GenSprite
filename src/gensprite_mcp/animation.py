"""Immutable native-grid motion packages, with reproducible technical checks."""

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from PIL import Image

from .knight import draw_knight
from .models import (
    AnimationFrame,
    AnimationManifest,
    AnimationRequest,
    AnimationResult,
    FrameAnimationRequest,
    FrameRect,
    Manifest,
    ValidationReport,
)

if TYPE_CHECKING:
    from .assets import AssetStore


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _visible_pixels(data: bytes) -> bytes:
    # GIF has one transparent index; invisible RGB is irrelevant to visual comparisons.
    pixels = bytearray(data)
    for index in range(0, len(pixels), 4):
        if pixels[index + 3] == 0:
            pixels[index : index + 3] = b"\x00\x00\x00"
    return bytes(pixels)


def _gif_frame(image: Image.Image, palette: list[str]) -> Image.Image:
    colors = [tuple(bytes.fromhex(color[1:])) for color in palette]
    indices = {rgb: i + 1 for i, rgb in enumerate(colors)}
    indexed = Image.new("P", image.size)
    flat = [0, 0, 0] + [component for rgb in colors for component in rgb]
    indexed.putpalette(flat + [0] * (768 - len(flat)))
    indexed.putdata([indices[(r, g, b)] if a else 0 for r, g, b, a in image.get_flattened_data()])
    indexed.info["transparency"] = 0
    return indexed


def generate_animation(store: "AssetStore", request: AnimationRequest) -> dict[str, Any]:
    source = store._manifest(request.asset_id)
    if source.template != "knight":
        raise ValueError("Animation currently supports the knight template only")
    source_report = store.validate_sprite(request.asset_id)
    if source_report["technical_status"] != "passed":
        raise ValueError(f"Master validation failed: {source_report['errors']}")
    if not is_native_knight(store, source):
        raise ValueError(
            "Edited source requires agent-supplied poses; native redraw would lose edits"
        )
    count = 4 if request.motion == "idle" else 6
    width, height = source.canvas.width, source.canvas.height
    images = [draw_knight(width, height, source.palette, request.motion, i) for i in range(count)]
    return _write_animation(
        store,
        source,
        images,
        [request.duration_ms] * count,
        request.motion,
        request.motion == "idle",
        "knight_v1",
    )


def is_native_knight(store: "AssetStore", source: Manifest) -> bool:
    if source.template != "knight" or min(source.canvas.width, source.canvas.height) < 32:
        return False
    with Image.open(store._path("generated", source.asset_id, "sprite.png")) as image:
        expected = draw_knight(source.canvas.width, source.canvas.height, source.palette)
        return image.mode == "RGBA" and image.tobytes() == expected.tobytes()


def assemble_animation(store: "AssetStore", request: FrameAnimationRequest) -> dict[str, Any]:
    source = store._manifest(request.asset_id)
    if store.validate_sprite(request.asset_id)["errors"]:
        raise ValueError("Master validation failed")
    images = _load_frames(store, source, request.frame_asset_ids)
    return _write_animation(
        store, source, images, request.durations_ms, request.name, request.loop,
        "agent_frames", request.frame_asset_ids, request.allow_duplicate_frames,
    )


def _load_frames(store: "AssetStore", source: Manifest, asset_ids: list[str]) -> list[Image.Image]:
    images = []
    for asset_id in asset_ids:
        manifest = store._manifest(asset_id)
        if store.validate_sprite(asset_id)["errors"]:
            raise ValueError(f"Frame source validation failed: {asset_id}")
        if manifest.canvas != source.canvas:
            raise ValueError("All animation frames must use the master canvas")
        with Image.open(store._path("generated", asset_id, "sprite.png")) as image:
            images.append(image.copy())
    return images


def validate_frames(
    source: Manifest, images: list[Image.Image], durations: list[int], motion: str,
    loop: bool, allow_duplicates: bool = False,
) -> None:
    """Preflight the whole motion before persisting poses or animation files."""
    FrameAnimationRequest(
        asset_id=source.asset_id, frame_asset_ids=[source.asset_id] * len(images),
        durations_ms=durations, name=motion, loop=loop, allow_duplicate_frames=allow_duplicates,
    )
    approved = {tuple(bytes.fromhex(color[1:])) for color in source.palette}
    for image in images:
        if image.size != (source.canvas.width, source.canvas.height) or image.mode != "RGBA":
            raise ValueError("Frames must match the native RGBA master canvas")
        alpha = image.getchannel("A")
        if not alpha.getbbox():
            raise ValueError("Frames must contain visible pixels")
        if source.transparent and alpha.getextrema()[0] != 0:
            raise ValueError("Frames require a transparent background like the master")
        if any(
            a not in (0, 255) or (a and (r, g, b) not in approved)
            for r, g, b, a in image.get_flattened_data()
        ):
            raise ValueError("Frame alpha or palette differs from the master rules")
    if (
        not allow_duplicates
        and len({_visible_pixels(image.tobytes()) for image in images}) != len(images)
    ):
        raise ValueError("Motion plan contains duplicate frames; express holds with durations")


def _write_animation(
    store: "AssetStore",
    source: Manifest,
    images: list[Image.Image],
    durations: list[int],
    motion: str,
    loop: bool,
    plan: str,
    frame_sources: list[str] | None = None,
    allow_duplicates: bool = False,
) -> dict[str, Any]:
    count = len(images)
    width, height = source.canvas.width, source.canvas.height
    validate_frames(source, images, durations, motion, loop, allow_duplicates)
    animation_id = f"n_{uuid4().hex}"
    manifest_path = store._path("animations", animation_id, "manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=False)
    strip = Image.new("RGBA", (width * count, height))
    records: list[AnimationFrame] = []
    paths: list[Path] = []
    for i, image in enumerate(images):
        path = store._path("animations", animation_id, f"{i:03}.png")
        with path.open("xb") as output:
            image.save(output, format="PNG")
        strip.paste(image, (i * width, 0))
        paths.append(path)
        records.append(
            AnimationFrame(
                file=path.name,
                duration_ms=durations[i],
                source_sha256=_digest(path),
                rect=FrameRect(x=i * width, width=width, height=height),
                source_asset_id=frame_sources[i] if frame_sources else None,
            )
        )
    strip_path = store._path("animations", animation_id, "spritesheet.png")
    with strip_path.open("xb") as output:
        strip.save(output, format="PNG")
    preview_path = store._path("animations", animation_id, "preview.gif")
    gif_frames = [_gif_frame(image, source.palette) for image in images]
    with preview_path.open("xb") as output:
        gif_frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=gif_frames[1:],
            duration=durations,
            loop=0,
            transparency=0,
            disposal=2,
            optimize=False,
        )
    manifest = AnimationManifest(
        animation_id=animation_id,
        source_asset_id=source.asset_id,
        source_sha256=source.source_sha256,
        motion=motion,
        loop=loop,
        motion_plan=plan,
        canvas=source.canvas,
        palette=source.palette,
        pivot=source.pivot,
        frames=records,
        transparent=source.transparent,
        allow_duplicate_frames=allow_duplicates,
        spritesheet_sha256=_digest(strip_path),
        preview_sha256=_digest(preview_path),
    )
    store._write_new(manifest_path, manifest)
    report = validate_animation(store, animation_id)
    if report["technical_status"] != "passed":
        raise ValueError(f"Generated animation failed validation: {report['errors']}")
    return AnimationResult(
        animation_id=animation_id,
        source_asset_id=source.asset_id,
        motion=motion,
        frame_count=count,
        frame_paths=paths,
        manifest_path=manifest_path,
        spritesheet_path=strip_path,
        preview_path=preview_path,
        validation=ValidationReport(**report),
    ).model_dump()


def validate_animation(store: "AssetStore", animation_id: str) -> dict[str, Any]:
    path = store._path("animations", animation_id, "manifest.json")
    manifest = store._read(path, AnimationManifest)
    if manifest.animation_id != animation_id:
        raise ValueError("Invalid manifest: animation ID does not match its directory")
    errors: list[str] = []
    try:
        source = store._manifest(manifest.source_asset_id)
        report = store.validate_sprite(manifest.source_asset_id)
        errors.extend(f"Master: {error}" for error in report["errors"])
        if (
            source.source_sha256 != manifest.source_sha256
            or source.canvas != manifest.canvas
            or source.palette != manifest.palette
            or source.pivot != manifest.pivot
            or (manifest.motion_plan == "knight_v1" and source.template != "knight")
        ):
            errors.append("Master reference metadata changed since animation creation")
    except ValueError as exc:
        errors.append(f"Master reference unavailable: {exc}")

    pixels: list[bytes | None] = []
    for record in manifest.frames:
        frame_path = store._path("animations", animation_id, record.file)
        rules = Manifest(
            asset_id=manifest.source_asset_id,
            description="Animation frame",
            canvas=manifest.canvas,
            palette=manifest.palette,
            pivot=manifest.pivot,
            source_sha256=record.source_sha256,
            transparent=manifest.transparent,
        )
        _, frame_errors = store._scan_file(frame_path, rules)
        errors.extend(f"{record.file}: {error}" for error in frame_errors)
        if frame_errors:
            pixels.append(None)
        else:
            with Image.open(frame_path) as image:
                pixels.append(image.tobytes())
        if record.source_asset_id:
            try:
                reference = store._manifest(record.source_asset_id)
                if (
                    store.validate_sprite(record.source_asset_id)["errors"]
                    or reference.source_sha256 != record.source_sha256
                ):
                    errors.append(f"{record.file}: frame source changed")
            except ValueError as exc:
                errors.append(f"{record.file}: frame source unavailable: {exc}")
    visual_pixels = [_visible_pixels(data) if data is not None else None for data in pixels]
    good_pixels = [data for data in visual_pixels if data is not None]
    if not manifest.allow_duplicate_frames and len(set(good_pixels)) != len(good_pixels):
        errors.append("Motion plan contains duplicate frames")

    for filename, digest, kind in [
        (manifest.spritesheet, manifest.spritesheet_sha256, "PNG"),
        (manifest.preview, manifest.preview_sha256, "GIF"),
    ]:
        output = store._path("animations", animation_id, filename)
        try:
            if output.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("exceeds the 4 MiB file limit")
            if _digest(output) != digest:
                raise ValueError("source digest changed")
            with Image.open(output) as image:
                count = len(manifest.frames)
                width, height = manifest.canvas.width, manifest.canvas.height
                expected = (width * count, height) if kind == "PNG" else (width, height)
                if image.format != kind or image.size != expected:
                    raise ValueError("format or dimensions do not match the manifest")
                if kind == "PNG":
                    if image.mode != "RGBA":
                        raise ValueError("sprite sheet must use RGBA")
                    for i, data in enumerate(pixels):
                        crop = image.crop((i * width, 0, (i + 1) * width, height))
                        if data is not None and crop.tobytes() != data:
                            raise ValueError(f"sprite sheet rectangle {i} differs from its frame")
                else:
                    if image.n_frames > count or (
                        not manifest.allow_duplicate_frames and image.n_frames != count
                    ):
                        raise ValueError("preview frame count differs from the motion plan")
                    decoded = []
                    for i in range(image.n_frames):
                        image.seek(i)
                        decoded.append(
                            (
                                image.info.get("duration", 0),
                                _visible_pixels(image.convert("RGBA").tobytes()),
                            )
                        )
                    if sum(t for t, _ in decoded) != sum(f.duration_ms for f in manifest.frames):
                        raise ValueError("preview total timing differs from frame durations")
                    elapsed = 0
                    cursor = 0
                    boundary = decoded[0][0]
                    for i, record in enumerate(manifest.frames):
                        while elapsed >= boundary and cursor < len(decoded) - 1:
                            cursor += 1
                            boundary += decoded[cursor][0]
                        if (
                            not manifest.allow_duplicate_frames
                            and decoded[i][0] != record.duration_ms
                        ):
                            raise ValueError(f"preview timing differs at frame {i}")
                        if visual_pixels[i] is not None and decoded[cursor][1] != visual_pixels[i]:
                            raise ValueError(f"preview pixels differ at frame {i}")
                        elapsed += record.duration_ms
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            errors.append(f"{filename}: {exc}")
    return store._report(animation_id, errors)
