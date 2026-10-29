"""Explicit conversion of client-generated PNGs into native sprite canvases."""

import asyncio
from pathlib import Path
from typing import Any

from PIL import Image

from .assets import AssetStore
from .image_ops import (
    MAX_PNG_BYTES,
    _cutoff,
    _decode_input,
    _decode_png,
    _integer,
    _palette,
    _quantize,
    _reduced_palette,
    _remove_matte,
    _rgb,
)
from .models import Canvas, Size


def fit_source(
    image: Image.Image, width: int, height: int, padding: int,
    background_color: str | None = None, background_tolerance: int = 0,
) -> Image.Image:
    """Keep the full frame and aspect ratio so separately prepared poses stay aligned."""
    Canvas(width=width, height=height)
    _integer(padding, "padding", 0, 32)
    if padding * 2 >= min(width, height):
        raise ValueError("padding must leave at least one pixel inside the canvas")
    _integer(background_tolerance, "background_tolerance", 0, 255)
    if background_color is None and background_tolerance:
        raise ValueError("background_tolerance requires background_color")
    if background_color is not None:
        _rgb(background_color)
    scale = min((width - 2 * padding) / image.width, (height - 2 * padding) / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resized = image.resize(size, Image.Resampling.NEAREST)
    if background_color is not None:
        _remove_matte(resized, background_color, background_tolerance)
    canvas = Image.new("RGBA", (width, height))
    canvas.paste(resized, ((width - size[0]) // 2, (height - size[1]) // 2))
    return canvas


def prepare_sprite(
    store: AssetStore, image: str | None = None, image_path: str | None = None,
    width: int = 32, height: int = 32, padding: int = 2,
    palette: list[str] | None = None, max_colors: int | None = None,
    alpha_cutoff: int = 128, background_color: str | None = None,
    background_tolerance: int = 0, display_name: str = "Prepared AI sprite",
) -> dict[str, Any]:
    """Prepare one PNG, retaining original bytes and reproducible placement metadata."""
    Canvas(width=width, height=height)
    _integer(alpha_cutoff, "alpha_cutoff", 1, 255)
    if palette is not None and max_colors is not None:
        raise ValueError("Specify palette or max_colors, not both")
    if palette is not None:
        palette = _palette(palette)
    else:
        max_colors = 16 if max_colors is None else _integer(max_colors, "max_colors", 1, 32)
    if (image is None) == (image_path is None):
        raise ValueError("Supply exactly one of image or image_path")
    if image_path is not None:
        path = Path(image_path)
        if (
            not path.is_absolute() or str(path).startswith(("\\\\", "//"))
            or path.suffix.lower() != ".png" or not path.is_file()
        ):
            raise ValueError("image_path must be an absolute local PNG file path")
        if path.stat().st_size > MAX_PNG_BYTES:
            raise ValueError("PNG exceeds the 4 MiB limit")
        with path.open("rb") as source:
            raw = source.read(MAX_PNG_BYTES + 1)
        decoded = _decode_png(raw, 4096)
    else:
        decoded, raw = _decode_input(image, 4096)
    placement = dict(
        width=width, height=height, padding=padding,
        background_color=background_color, background_tolerance=background_tolerance,
    )
    processed = _cutoff(fit_source(decoded, **placement), alpha_cutoff)
    if palette is None:
        palette = _reduced_palette(processed, max_colors)
    processed = _quantize(processed, palette)
    return store.save_image(
        processed, display_name, palette=palette, template="imported",
        source_png=raw,
        metadata={
            "operation": "prepare_sprite",
            "original_canvas": {"width": decoded.width, "height": decoded.height},
            "preparation": placement, "alpha_cutoff": alpha_cutoff,
        },
    )


def register_preparation_tool(server, store: AssetStore) -> None:
    @server.tool(name="prepare_sprite")
    async def prepare_tool(
        image: str | None = None, image_path: str | None = None,
        width: Size = 32, height: Size = 32, padding: int = 2,
        palette: list[str] | None = None, max_colors: int | None = None,
        alpha_cutoff: int = 128, background_color: str | None = None,
        background_tolerance: int = 0, display_name: str = "Prepared AI sprite",
    ) -> dict[str, Any]:
        """Prepare an AI PNG (8..4096px, <=4 MiB) for a native 8..256px sprite canvas.

        Supply base64 image OR an absolute local image_path. Fits the full image with
        nearest-neighbor pixels and padding; keeps original bytes. Uses binary alpha and
        no dithering, with an explicit palette or max_colors (default 16). Optional matte
        removal is border-connected, not AI segmentation. Consistent source framing and
        identical settings preserve pose alignment. Call review_asset to inspect the result;
        downsampling cannot invent good artwork. Use import_asset for exact native pixels.
        """
        return await asyncio.to_thread(
            prepare_sprite, store, image, image_path, width, height, padding, palette,
            max_colors, alpha_cutoff, background_color, background_tolerance, display_name,
        )
