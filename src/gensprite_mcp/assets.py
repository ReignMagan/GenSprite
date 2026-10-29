"""Native-grid drawing, bounded local persistence, and technical validation."""

import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageDraw, UnidentifiedImageError
from pydantic import ValidationError

from .knight import KNIGHT_PALETTE, draw_knight
from .models import (
    DEFAULT_PALETTE,
    AnimationManifest,
    AnimationRequest,
    Canvas,
    FrameAnimationRequest,
    Manifest,
    Pivot,
    ProjectProfile,
    SpriteRequest,
    SpriteResult,
    ValidationReport,
)


class AssetStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, kind: str, identifier: str, filename: str) -> Path:
        prefix = {
            "profiles": "p",
            "generated": "a",
            "animations": "n",
            "runs": "r",
            "uploads": "t",
            "ui_kits": "u",
            "reports": "i",
        }[kind]
        if not re.fullmatch(rf"{prefix}_[0-9a-f]{{32}}", identifier):
            raise ValueError("Invalid ID; use the generated profile or asset ID, not a path")
        path = self.root / kind / identifier / filename
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Asset path escapes the configured output directory")
        for part in [path, *path.parents]:
            if part == self.root:
                break
            if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                raise ValueError("Symlinks are not allowed inside the output directory")
        return path

    @staticmethod
    def _read(
        path: Path,
        model: type[ProjectProfile] | type[Manifest] | type[AnimationManifest],
    ) -> Any:
        try:
            if path.stat().st_size > 65536:
                raise ValueError("JSON file exceeds the 64 KiB limit")
            return model.model_validate_json(path.read_bytes())
        except FileNotFoundError as exc:
            raise ValueError(f"{path.name} not found") from exc
        except (OSError, ValidationError, ValueError) as exc:
            raise ValueError(f"Invalid {path.name}: {exc}") from exc

    @staticmethod
    def _write_new(path: Path, model: ProjectProfile | Manifest | AnimationManifest) -> None:
        with path.open("x", encoding="utf-8") as output:
            output.write(model.model_dump_json(indent=2))

    def create_project_profile(self, profile: ProjectProfile) -> dict[str, str]:
        profile_id = f"p_{uuid4().hex}"
        path = self._path("profiles", profile_id, "profile.json")
        path.parent.mkdir(parents=True, exist_ok=False)
        self._write_new(path, profile)
        return {"profile_id": profile_id}

    def get_project_profile(self, profile_id: str) -> ProjectProfile:
        return self._read(self._path("profiles", profile_id, "profile.json"), ProjectProfile)

    def save_image(
        self,
        image: Image.Image,
        description: str,
        palette: list[str] | None = None,
        template: str = "agent",
        asset_type: str = "character",
        parent_asset_id: str | None = None,
        metadata: dict | None = None,
        source_png: bytes | None = None,
    ) -> dict[str, Any]:
        canvas = Canvas(width=image.width, height=image.height)
        image = image.convert("RGBA")
        colors_and_counts = image.getcolors(maxcolors=image.width * image.height)
        alpha = {pixel[3] for _, pixel in colors_and_counts}
        if not alpha <= {0, 255}:
            raise ValueError("Nonbinary alpha; explicitly refine with an alpha cutoff")
        colors = sorted({
            f"#{r:02X}{g:02X}{b:02X}" for _, (r, g, b, a) in colors_and_counts if a
        })
        if not colors:
            raise ValueError("Image must contain visible pixels")
        if palette is not None and set(colors) - {color.upper() for color in palette}:
            raise ValueError("Image uses colors outside the locked palette")
        if parent_asset_id and self.validate_sprite(parent_asset_id)["errors"]:
            raise ValueError("Parent source validation failed")
        details = dict(metadata or {})
        if source_png is not None:
            if not isinstance(source_png, bytes) or len(source_png) > 4 * 1024 * 1024:
                raise ValueError("Original PNG must be bytes no larger than 4 MiB")
            details["original_sha256"] = hashlib.sha256(source_png).hexdigest()
            details.pop("original_asset_id", None)
        if len(json.dumps(details).encode("utf-8")) > 16384:
            raise ValueError("Asset metadata exceeds 16 KiB")
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        asset_id = f"a_{uuid4().hex}"
        manifest = Manifest(
            asset_id=asset_id,
            description=description,
            canvas=canvas,
            palette=palette or colors,
            pivot=Pivot(x=image.width // 2, y=image.height - 1),
            template=template,
            type=asset_type,
            transparent=0 in alpha,
            parent_asset_id=parent_asset_id,
            metadata=details,
            source_sha256=hashlib.sha256(encoded.getvalue()).hexdigest(),
            history=[
                "Created by agent-supplied artwork"
                if not parent_asset_id
                else f"Immutable revision of {parent_asset_id}"
            ],
        )
        png_path = self._path("generated", asset_id, "sprite.png")
        manifest_path = self._path("generated", asset_id, "manifest.json")
        png_path.parent.mkdir(parents=True, exist_ok=False)
        with png_path.open("xb") as output:
            output.write(encoded.getvalue())
        if source_png is not None:
            source_path = self._path("generated", asset_id, "source.png")
            with source_path.open("xb") as output:
                output.write(source_png)
        self._write_new(manifest_path, manifest)
        report = self.validate_sprite(asset_id)
        if report["errors"]:
            raise ValueError(f"Image validation failed: {report['errors']}")
        return SpriteResult(
            asset_id=asset_id,
            png_path=png_path,
            manifest_path=manifest_path,
            validation=ValidationReport(**report),
        ).model_dump()

    def create_sprite(self, request: SpriteRequest) -> dict[str, Any]:
        default = KNIGHT_PALETTE if request.template == "knight" else DEFAULT_PALETTE
        palette = request.palette if request.palette is not None else default.copy()
        if request.profile_id:
            profile = self.get_project_profile(request.profile_id)
            if request.palette is not None and request.palette != profile.palette:
                raise ValueError("Requested palette does not match the locked project palette")
            if Canvas(width=request.width, height=request.height) not in profile.sizes:
                raise ValueError("Requested canvas is not in the project's allowed sizes")
            palette = profile.palette
        if request.template == "knight":
            image = draw_knight(request.width, request.height, palette)
        else:
            image = Image.new("RGBA", (request.width, request.height))
            draw = ImageDraw.Draw(image)

            def polygon(points: list[tuple[int, int]], color: str) -> None:
                draw.polygon(
                    [(x * request.width // 16, y * request.height // 16) for x, y in points],
                    fill=color,
                )

            outline = palette[0]
            fill = palette[min(1, len(palette) - 1)]
            highlight = palette[min(2, len(palette) - 1)]
            polygon(
                [
                    (2, 3),
                    (5, 3),
                    (7, 5),
                    (8, 5),
                    (10, 3),
                    (13, 3),
                    (14, 4),
                    (14, 8),
                    (8, 14),
                    (7, 14),
                    (1, 8),
                    (1, 4),
                ],
                outline,
            )
            polygon(
                [
                    (3, 4),
                    (5, 4),
                    (7, 6),
                    (8, 6),
                    (10, 4),
                    (12, 4),
                    (13, 5),
                    (13, 8),
                    (8, 13),
                    (7, 13),
                    (2, 8),
                    (2, 5),
                ],
                fill,
            )
            polygon([(3, 5), (5, 5), (5, 6), (4, 6), (4, 7), (3, 7)], highlight)

        asset_id = f"a_{uuid4().hex}"
        png_path = self._path("generated", asset_id, "sprite.png")
        manifest_path = self._path("generated", asset_id, "manifest.json")
        png_path.parent.mkdir(parents=True, exist_ok=False)
        with png_path.open("xb") as output:
            image.save(output, format="PNG")
        manifest = Manifest(
            asset_id=asset_id,
            description=request.description,
            canvas=Canvas(width=request.width, height=request.height),
            palette=palette,
            pivot=Pivot(x=request.width // 2, y=request.height - 1),
            profile_id=request.profile_id,
            source_sha256=hashlib.sha256(png_path.read_bytes()).hexdigest(),
            template=request.template,
            type="character" if request.template == "knight" else "icon",
            history=[f"Created from native-grid {request.template} template"],
        )
        self._write_new(manifest_path, manifest)
        report = self.validate_sprite(asset_id)
        if report["technical_status"] != "passed":
            raise ValueError(f"Generated sprite failed validation: {report['errors']}")
        return SpriteResult(
            asset_id=asset_id,
            png_path=png_path,
            manifest_path=manifest_path,
            validation=ValidationReport(**report),
        ).model_dump()

    def _manifest(self, asset_id: str) -> Manifest:
        manifest = self._read(self._path("generated", asset_id, "manifest.json"), Manifest)
        if manifest.asset_id != asset_id:
            raise ValueError("Invalid manifest: asset ID does not match its directory")
        return manifest

    def _scan(self, asset_id: str, manifest: Manifest) -> tuple[dict[str, Any], list[str]]:
        path = self._path("generated", asset_id, "sprite.png")
        return self._scan_file(path, manifest)

    @staticmethod
    def _scan_file(path: Path, manifest: Manifest) -> tuple[dict[str, Any], list[str]]:
        errors: list[str] = []
        info: dict[str, Any] = {}
        try:
            if path.stat().st_size > 4 * 1024 * 1024:
                return info, ["PNG exceeds the 4 MiB file limit"]
            with path.open("rb") as source:
                raw = source.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                return info, ["PNG exceeds the 4 MiB file limit"]
            with Image.open(io.BytesIO(raw)) as image:
                info.update(
                    format=image.format, mode=image.mode, width=image.width, height=image.height
                )
                if image.format != "PNG":
                    errors.append("Image must be encoded as PNG")
                if image.mode != "RGBA":
                    errors.append("Image must use RGBA mode")
                if image.size != (manifest.canvas.width, manifest.canvas.height):
                    errors.append("Image dimensions do not match the manifest canvas")
                if image.width > 256 or image.height > 256:
                    return info, errors + ["Image dimensions exceed the 256-pixel limit"]
                unique = image.convert("RGBA").getcolors(maxcolors=image.width * image.height)
                alpha = {pixel[3] for _, pixel in unique}
                colors = sorted({f"#{r:02X}{g:02X}{b:02X}" for _, (r, g, b, a) in unique if a})
                info.update(colors=colors, alpha_values=sorted(alpha))
                if not alpha <= {0, 255}:
                    errors.append("Image has nonbinary alpha; remove semitransparent pixels")
                if manifest.transparent and 0 not in alpha:
                    errors.append("Image requires a transparent background")
                if not colors:
                    errors.append("Image must contain visible pixels")
                if set(colors) - set(manifest.palette):
                    errors.append("Image uses colors outside the locked palette")
            if hashlib.sha256(raw).hexdigest() != manifest.source_sha256:
                errors.append(
                    "PNG source digest changed; preserve the original and create a revision"
                )
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError, ValueError) as exc:
            errors.append(f"Cannot read valid PNG: {exc}")
        return info, errors

    @staticmethod
    def _report(asset_id: str, errors: list[str]) -> dict[str, Any]:
        return ValidationReport(
            asset_id=asset_id,
            technical_status="failed" if errors else "passed",
            status="failed" if errors else "ready_for_export",
            errors=errors,
            approval_source=None if errors else "automated_technical_checks",
        ).model_dump()

    def inspect_sprite(self, asset_id: str) -> dict[str, Any]:
        manifest = self._manifest(asset_id)
        info, errors = self._scan(asset_id, manifest)
        return {
            "asset_id": asset_id,
            **info,
            "manifest": manifest.model_dump(),
            "validation": self._report(asset_id, errors),
        }

    def validate_sprite(self, asset_id: str) -> dict[str, Any]:
        manifest = self._manifest(asset_id)
        _, errors = self._scan(asset_id, manifest)
        return self._report(asset_id, errors)

    def generate_animation(self, request: AnimationRequest) -> dict[str, Any]:
        from .animation import generate_animation

        return generate_animation(self, request)

    def validate_animation(self, animation_id: str) -> dict[str, Any]:
        from .animation import validate_animation

        return validate_animation(self, animation_id)

    def assemble_animation(self, request: FrameAnimationRequest) -> dict[str, Any]:
        from .animation import assemble_animation

        return assemble_animation(self, request)
