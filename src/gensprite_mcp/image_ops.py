"""Bounded PNG imports and explicit, immutable local image operations."""

import base64
import binascii
import hashlib
import io
import struct
from collections import deque
from typing import Annotated, Any, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from .assets import AssetStore
from .models import Canvas, Color, Manifest, Palette, normalize_palette

MAX_PNG_BYTES = 4 * 1024 * 1024
MAX_BASE64_LENGTH = 4 * ((MAX_PNG_BYTES + 2) // 3)
_PALETTE = TypeAdapter(Palette)
_COLOR = TypeAdapter(Color)


class _Edit(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)


class _Crop(_Edit):
    op: Literal["crop"]
    x: int = Field(ge=0, le=255)
    y: int = Field(ge=0, le=255)
    width: int = Field(ge=8, le=256)
    height: int = Field(ge=8, le=256)


class _Recolor(_Edit):
    op: Literal["recolor"]
    from_color: Color = Field(alias="from")
    to: Color

    @field_validator("from_color", "to")
    @classmethod
    def uppercase(cls, value: str) -> str:
        return value.upper()


class _Flip(_Edit):
    op: Literal["flip"]
    axis: Literal["horizontal", "vertical"]


class _Pixel(_Edit):
    x: int = Field(ge=0, le=255)
    y: int = Field(ge=0, le=255)
    color: Color | None


class _SetPixels(_Edit):
    op: Literal["set_pixels"]
    pixels: list[_Pixel] = Field(min_length=1, max_length=65536)


_EDITS = TypeAdapter(Annotated[
    list[Annotated[_Crop | _Recolor | _Flip | _SetPixels, Field(discriminator="op")]],
    Field(min_length=1, max_length=64, strict=True),
])


def _integer(value: int, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def _rgb(color: str) -> tuple[int, int, int]:
    color = _COLOR.validate_python(color, strict=True)
    return tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))


def _palette(palette: list[str]) -> list[str]:
    return normalize_palette(_PALETTE.validate_python(palette, strict=True))


def _decode_png(raw: bytes, max_dimension: int = 256) -> Image.Image:
    if len(raw) > MAX_PNG_BYTES:
        raise ValueError("PNG exceeds the 4 MiB limit")
    if len(raw) < 33 or raw[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise ValueError("Input must be a valid PNG")
    width, height = struct.unpack(">II", raw[16:24])
    if not 8 <= width <= max_dimension or not 8 <= height <= max_dimension:
        raise ValueError(f"PNG canvas dimensions must be between 8 and {max_dimension} pixels")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Import requires a single PNG frame; animated PNG is unsupported")
            if image.size != (width, height):
                raise ValueError("PNG dimensions disagree with the IHDR canvas")
            image.load()
            return image.convert("RGBA")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Cannot decode valid PNG: {exc}") from exc


def _decode_input(image: str, max_dimension: int = 256) -> tuple[Image.Image, bytes]:
    if not isinstance(image, str):
        raise ValueError("image must be base64 PNG text or a data:image/png;base64 URL")
    if image.startswith("data:"):
        prefix = "data:image/png;base64,"
        if not image.startswith(prefix):
            raise ValueError("Only data:image/png;base64 URLs are supported")
        image = image[len(prefix):]
    if len(image) > MAX_BASE64_LENGTH:
        raise ValueError("PNG exceeds the 4 MiB limit")
    try:
        raw = base64.b64decode(image, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            "image must contain valid base64 PNG data; remote URLs are unsupported"
        ) from exc
    return _decode_png(raw, max_dimension), raw


def _cutoff(image: Image.Image, alpha_cutoff: int | None) -> Image.Image:
    if alpha_cutoff is None:
        if not set(image.getchannel("A").get_flattened_data()) <= {0, 255}:
            raise ValueError(
                "PNG has nonbinary alpha; supply an explicit alpha_cutoff from 1 to 255"
            )
        return image.copy()
    _integer(alpha_cutoff, "alpha_cutoff", 1, 255)
    result = image.copy()
    result.putalpha(image.getchannel("A").point(lambda alpha: 255 if alpha >= alpha_cutoff else 0))
    return result


def _quantize(image: Image.Image, palette: list[str]) -> Image.Image:
    palette = _palette(palette)
    colors = [_rgb(color) for color in palette]
    nearest: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    pixels = []
    for red, green, blue, alpha in image.get_flattened_data():
        if not alpha:
            pixels.append((red, green, blue, 0))
            continue
        rgb = (red, green, blue)
        if rgb not in nearest:
            nearest[rgb] = min(colors, key=lambda color: (
                (red - color[0]) ** 2 + (green - color[1]) ** 2 + (blue - color[2]) ** 2
            ))
        pixels.append((*nearest[rgb], alpha))
    result = Image.new("RGBA", image.size)
    result.putdata(pixels)
    return result


def _reduced_palette(image: Image.Image, max_colors: int) -> list[str]:
    _integer(max_colors, "max_colors", 1, 32)
    visible = [pixel[:3] for pixel in image.get_flattened_data() if pixel[3]]
    if not visible:
        raise ValueError("Color reduction must preserve visible pixels")
    strip = Image.new("RGB", (len(visible), 1))
    strip.putdata(visible)
    reduced = strip.quantize(colors=max_colors, dither=Image.Dither.NONE).convert("RGB")
    return sorted({"#%02X%02X%02X" % color for color in reduced.get_flattened_data()})


def _load_asset(store: AssetStore, asset_id: str) -> tuple[Manifest, Image.Image]:
    manifest = store._manifest(asset_id)
    report = store.validate_sprite(asset_id)
    if report["technical_status"] != "passed":
        raise ValueError(f"Source asset failed technical validation: {report['errors']}")
    path = store._path("generated", asset_id, "sprite.png")
    return manifest, _decode_png(path.read_bytes())


def _original_image(store: AssetStore, manifest: Manifest, fallback: Image.Image) -> Image.Image:
    digest = manifest.metadata.get("original_sha256")
    if digest is None:
        return fallback
    original_id = manifest.metadata.get("original_asset_id", manifest.asset_id)
    if not isinstance(original_id, str):
        raise ValueError("Preserved original asset ID is invalid")
    original = store._path("generated", original_id, "source.png")
    try:
        if original.stat().st_size > MAX_PNG_BYTES:
            raise ValueError("Original PNG exceeds the 4 MiB limit")
        raw = original.read_bytes()
    except OSError as exc:
        raise ValueError(f"Preserved original PNG is unavailable: {exc}") from exc
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Preserved original PNG digest changed")
    if "preparation" in manifest.metadata:
        from .preparation import fit_source

        return fit_source(_decode_png(raw, 4096), **manifest.metadata["preparation"])
    return _decode_png(raw)


def _metadata(manifest: Manifest, operation: str, **details: Any) -> dict[str, Any]:
    metadata = dict(manifest.metadata)
    if "original_sha256" in metadata:
        metadata.setdefault("original_asset_id", manifest.asset_id)
    metadata.update(operation=operation, **details)
    return metadata


def _save_revision(
    store: AssetStore, manifest: Manifest, image: Image.Image, operation: str,
    palette: list[str] | None = None, **details: Any,
) -> dict[str, Any]:
    return store.save_image(
        image, description=manifest.description,
        palette=manifest.palette if palette is None else palette,
        template=manifest.template, asset_type=manifest.type, parent_asset_id=manifest.asset_id,
        metadata=_metadata(manifest, operation, **details),
    )


def import_image(
    store: AssetStore, image: str, display_name: str = "Imported sprite",
    palette: list[str] | None = None, alpha_cutoff: int | None = None,
    *, description: str | None = None, asset_type: str = "character",
    parent_asset_id: str | None = None, metadata: dict | None = None, canvas: Canvas | None = None,
) -> dict[str, Any]:
    """Import base64/data-URL PNG, preserving source bytes; cleanup requires explicit inputs."""
    decoded, raw = _decode_input(image)
    if canvas is not None and decoded.size != (canvas.width, canvas.height):
        raise ValueError("Imported image dimensions differ from the requested canvas")
    processed = _cutoff(decoded, alpha_cutoff)
    if palette is not None:
        palette = _palette(palette)
        processed = _quantize(processed, palette)
    metadata = {**(metadata or {}), "operation": "import"}
    if alpha_cutoff is not None:
        metadata["alpha_cutoff"] = alpha_cutoff
    return store.save_image(
        processed, description=description or display_name, palette=palette, template="imported",
        asset_type=asset_type, parent_asset_id=parent_asset_id, metadata=metadata, source_png=raw,
    )


import_asset = import_image


def edit_sprite(store: AssetStore, asset_id: str, edits: list[dict]) -> dict[str, Any]:
    """Apply ordered crop/recolor/flip/set_pixels operations without changing the palette."""
    operations = _EDITS.validate_python(edits, strict=True)
    if sum(len(edit.pixels) for edit in operations if isinstance(edit, _SetPixels)) > 65536:
        raise ValueError("An edit batch can set at most 65536 pixels")
    manifest, image = _load_asset(store, asset_id)
    for edit in operations:
        if isinstance(edit, _Crop):
            if edit.x + edit.width > image.width or edit.y + edit.height > image.height:
                raise ValueError("Crop bounds must stay inside the current canvas")
            image = image.crop((edit.x, edit.y, edit.x + edit.width, edit.y + edit.height))
        elif isinstance(edit, _Flip):
            method = Image.Transpose.FLIP_LEFT_RIGHT if edit.axis == "horizontal" else (
                Image.Transpose.FLIP_TOP_BOTTOM
            )
            image = image.transpose(method)
        elif isinstance(edit, _Recolor):
            if edit.from_color not in manifest.palette or edit.to not in manifest.palette:
                raise ValueError(
                    "Recolor colors must belong to the locked palette; use refine_sprite"
                )
            old, new = _rgb(edit.from_color), _rgb(edit.to)
            image.putdata([
                (*new, pixel[3]) if pixel[3] and pixel[:3] == old else pixel
                for pixel in image.get_flattened_data()
            ])
        else:
            for pixel in edit.pixels:
                if pixel.x >= image.width or pixel.y >= image.height:
                    raise ValueError("Pixel bounds must stay inside the current canvas")
                if pixel.color is not None and pixel.color.upper() not in manifest.palette:
                    raise ValueError("Pixel color must belong to the locked palette")
                color = (0, 0, 0, 0) if pixel.color is None else (*_rgb(pixel.color), 255)
                image.putpixel((pixel.x, pixel.y), color)
    return _save_revision(store, manifest, image, "edit_sprite", edit_count=len(operations))


def refine_sprite(
    store: AssetStore, asset_id: str, palette: list[str] | None = None,
    max_colors: int | None = None, alpha_cutoff: int | None = None,
) -> dict[str, Any]:
    """Explicitly threshold alpha and/or quantize colors without dithering or rescaling.

    Alpha cutoff reprocesses preserved import pixels/canvas when available; intermediate
    spatial edits and background removal must be reapplied afterward.
    """
    if palette is None and max_colors is None and alpha_cutoff is None:
        raise ValueError("Specify palette, max_colors, or alpha_cutoff to refine")
    if palette is not None and max_colors is not None:
        raise ValueError("Specify either a fixed palette or max_colors, not both")
    manifest, image = _load_asset(store, asset_id)
    if alpha_cutoff is not None:
        _integer(alpha_cutoff, "alpha_cutoff", 1, 255)
        image = _original_image(store, manifest, image)
    image = _cutoff(image, alpha_cutoff)
    if max_colors is not None:
        palette = _reduced_palette(image, max_colors)
    if palette is not None:
        palette = _palette(palette)
        image = _quantize(image, palette)
    elif alpha_cutoff is not None:
        image = _quantize(image, manifest.palette)
    return _save_revision(
        store, manifest, image, "refine_sprite", palette=palette,
        alpha_cutoff=alpha_cutoff, max_colors=max_colors,
    )


def remove_background(
    store: AssetStore, asset_id: str, color: str, tolerance: int = 0,
) -> dict[str, Any]:
    """Remove only border-connected pixels within per-channel RGB tolerance of a matte."""
    manifest, image = _load_asset(store, asset_id)
    removed = _remove_matte(image, color, tolerance)
    return _save_revision(
        store, manifest, image, "remove_background", background_color=color.upper(),
        background_tolerance=tolerance, removed_pixels=removed,
    )


def _remove_matte(image: Image.Image, color: str, tolerance: int = 0) -> int:
    """Mutate a native-size image, removing only the border-connected matte."""
    matte = _rgb(color)
    _integer(tolerance, "tolerance", 0, 255)
    pixels = image.load()
    queue = deque([(x, y) for x in range(image.width) for y in (0, image.height - 1)])
    queue.extend((x, y) for y in range(image.height) for x in (0, image.width - 1))
    visited = set()
    removed = 0
    # shortcut: simple border matte only; use agent-authored masks for complex backgrounds.
    while queue:
        x, y = queue.popleft()
        if (x, y) in visited:
            continue
        visited.add((x, y))
        pixel = pixels[x, y]
        if pixel[3] and any(abs(a - b) > tolerance for a, b in zip(pixel[:3], matte, strict=True)):
            continue
        if pixel[3]:
            pixels[x, y] = (*pixel[:3], 0)
            removed += 1
        queue.extend((nx, ny) for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                     if 0 <= nx < image.width and 0 <= ny < image.height)
    return removed


def set_asset_alpha_cutoff(
    store: AssetStore, asset_id: str, alpha_cutoff: int,
) -> dict[str, Any]:
    """Reprocess the preserved import, when available, into a new alpha-threshold version.

    Reprocessing uses the original canvas/pixels and the current locked palette; spatial
    edits and background removals from intermediate versions must be reapplied afterward.
    """
    _integer(alpha_cutoff, "alpha_cutoff", 1, 255)
    manifest, image = _load_asset(store, asset_id)
    image = _original_image(store, manifest, image)
    image = _quantize(_cutoff(image, alpha_cutoff), manifest.palette)
    return _save_revision(
        store, manifest, image, "set_asset_alpha_cutoff", alpha_cutoff=alpha_cutoff,
    )


def get_asset_history(store: AssetStore, asset_id: str) -> dict[str, Any]:
    """Return the immutable version ancestry, newest first, with cycle and depth checks."""
    versions = []
    seen = set()
    current = asset_id
    while current is not None:
        if current in seen:
            raise ValueError("Asset history contains a parent cycle")
        if len(versions) >= 1024:
            raise ValueError("Asset history exceeds the 1024-version limit")
        seen.add(current)
        manifest = store._manifest(current)
        versions.append({
            "asset_id": manifest.asset_id, "parent_asset_id": manifest.parent_asset_id,
            "description": manifest.description, "source_sha256": manifest.source_sha256,
            "metadata": manifest.metadata,
        })
        current = manifest.parent_asset_id
    return {"asset_id": asset_id, "versions": versions}


def rollback_asset(store: AssetStore, asset_id: str, target_asset_id: str) -> dict[str, Any]:
    """Copy an ancestor's pixels into a new child of the current version; never overwrite."""
    history = get_asset_history(store, asset_id)
    if target_asset_id not in {version["asset_id"] for version in history["versions"][1:]}:
        raise ValueError("Rollback target must be an ancestor in this asset's history")
    current, _ = _load_asset(store, asset_id)
    target, image = _load_asset(store, target_asset_id)
    return store.save_image(
        image, description=target.description, palette=target.palette, template=target.template,
        asset_type=target.type, parent_asset_id=current.asset_id,
        metadata=_metadata(target, "rollback_asset", rollback_target_asset_id=target_asset_id),
    )


def auto_slice_asset(store: AssetStore, asset_id: str, max_slices: int = 64) -> dict[str, Any]:
    """Slice every 8-connected alpha component, preserving pixels and padding canvases to 8px."""
    _integer(max_slices, "max_slices", 1, 256)
    manifest, image = _load_asset(store, asset_id)
    alpha = image.getchannel("A")
    remaining = {(x, y) for y in range(image.height) for x in range(image.width)
                 if alpha.getpixel((x, y))}
    components = []
    for seed in sorted(remaining, key=lambda point: (point[1], point[0])):
        if seed not in remaining:
            continue
        remaining.remove(seed)
        points = [seed]
        queue = deque([seed])
        while queue:
            x, y = queue.popleft()
            for ny in range(y - 1, y + 2):
                for nx in range(x - 1, x + 2):
                    if (nx, ny) in remaining:
                        remaining.remove((nx, ny))
                        points.append((nx, ny))
                        queue.append((nx, ny))
        components.append(points)
        if len(components) > max_slices:
            raise ValueError("Connected component count exceeds max_slices; no slices were written")
    slices = []
    for points in components:
        left, top = min(x for x, _ in points), min(y for _, y in points)
        width = max(x for x, _ in points) - left + 1
        height = max(y for _, y in points) - top + 1
        rect = {"x": left, "y": top, "width": width, "height": height}
        output = Image.new("RGBA", (max(8, width), max(8, height)))
        for x, y in points:
            output.putpixel((x - left, y - top), image.getpixel((x, y)))
        saved = _save_revision(store, manifest, output, "auto_slice_asset", source_rect=rect)
        slices.append({**saved, "rect": rect})
    return {"asset_id": asset_id, "slice_count": len(slices), "slices": slices}


def register_image_tools(server: Any, store: AssetStore) -> None:
    """Expose explicit image processing and revision tools over MCP."""

    @server.tool(name="import_asset")
    def import_tool(
        image: str, display_name: str = "Imported sprite", palette: list[str] | None = None,
        alpha_cutoff: int | None = None,
    ) -> dict[str, Any]:
        """Import <=4 MiB base64 PNG (8..256px), preserving original. No remote URLs.

        palette explicitly quantizes RGB without dithering; alpha_cutoff (1..255) explicitly
        converts soft alpha. Omitting them keeps exact pixels and rejects nonbinary alpha.
        """
        return import_image(store, image, display_name, palette, alpha_cutoff)

    @server.tool(name="edit_sprite")
    def edit_tool(asset_id: str, edits: list[dict]) -> dict[str, Any]:
        """New revision; ordered edits: crop{x,y,width,height}, recolor{from,to},
        flip{axis:horizontal|vertical}, set_pixels{pixels:[{x,y,color:#RRGGBB|null}]}.
        Each edit has op. Canvas 8..256; colors must stay in the locked palette.
        """
        return edit_sprite(store, asset_id, edits)

    @server.tool(name="refine_sprite")
    def refine_tool(
        asset_id: str, palette: list[str] | None = None, max_colors: int | None = None,
        alpha_cutoff: int | None = None,
    ) -> dict[str, Any]:
        """New revision: explicit fixed-palette or max_colors (1..32) RGB quantization,
        and/or binary alpha cutoff. No dithering, rescaling, or artistic-quality claim.
        Cutoff reprocesses the original import canvas/pixels; reapply intermediate edits.
        """
        return refine_sprite(store, asset_id, palette, max_colors, alpha_cutoff)

    @server.tool(name="remove_background")
    def background_tool(asset_id: str, color: str, tolerance: int = 0) -> dict[str, Any]:
        """New revision using simple border-connected matte removal, not AI segmentation.
        color is #RRGGBB; tolerance 0..255 is the maximum difference per RGB channel.
        """
        return remove_background(store, asset_id, color, tolerance)

    @server.tool(name="set_asset_alpha_cutoff")
    def cutoff_tool(asset_id: str, alpha_cutoff: int) -> dict[str, Any]:
        """New version thresholding preserved original alpha at 1..255. Original canvas
        and pixels replace intermediate spatial edits; current palette is retained.
        """
        return set_asset_alpha_cutoff(store, asset_id, alpha_cutoff)

    @server.tool(name="auto_slice_asset")
    def slice_tool(asset_id: str, max_slices: int = 64) -> dict[str, Any]:
        """New assets for all 8-connected alpha components, padded to >=8px. Limit 1..256;
        exceeding it fails before writing. Source rectangles preserve placement metadata.
        """
        return auto_slice_asset(store, asset_id, max_slices)

    @server.tool(name="get_asset_history")
    def history_tool(asset_id: str) -> dict[str, Any]:
        """Read immutable parent ancestry newest first, with descriptions and operation metadata."""
        return get_asset_history(store, asset_id)

    @server.tool(name="rollback_asset")
    def rollback_tool(asset_id: str, target_asset_id: str) -> dict[str, Any]:
        """Copy an ancestor into a new immutable version whose parent is asset_id."""
        return rollback_asset(store, asset_id, target_asset_id)
