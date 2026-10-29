"""Validated inputs and the portable still-sprite contract."""

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, field_validator, model_validator

Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Palette = Annotated[list[Color], Field(min_length=1, max_length=32)]
Size = Annotated[int, Field(strict=True, ge=8, le=256)]
ProfileId = Annotated[str, Field(pattern=r"^p_[0-9a-f]{32}$")]
AssetId = Annotated[str, Field(pattern=r"^a_[0-9a-f]{32}$")]
AnimationId = Annotated[str, Field(pattern=r"^n_[0-9a-f]{32}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Duration = Annotated[int, Field(strict=True, ge=10, le=10000, multiple_of=10)]
LocalPath = Annotated[Path, WithJsonSchema({"type": "string"})]
DEFAULT_PALETTE = ["#7F1D1D", "#EF4444", "#FCA5A5"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def normalize_palette(palette: list[str]) -> list[str]:
    colors = [color.upper() for color in palette]
    if len(set(colors)) != len(colors):
        raise ValueError("palette colors must be distinct")
    return colors


class Canvas(Model):
    width: Size = 32
    height: Size = 32


class ProjectProfile(Model):
    name: str = Field(min_length=1, max_length=100)
    palette: Palette = Field(default_factory=lambda: DEFAULT_PALETTE.copy())
    perspective: Literal["front"] = "front"
    sizes: list[Canvas] = Field(
        default_factory=lambda: [Canvas(width=16, height=16), Canvas()],
        min_length=1,
        max_length=16,
    )

    _normalize_palette = field_validator("palette")(normalize_palette)


class SpriteRequest(Canvas):
    template: Literal["heart", "knight"] = "heart"
    description: str = Field(
        default="A transparent pixel-art sprite",
        min_length=1,
        max_length=2000,
    )
    palette: Palette | None = None
    profile_id: ProfileId | None = None

    @field_validator("palette")
    @classmethod
    def validate_palette(cls, palette: list[str] | None) -> list[str] | None:
        return None if palette is None else normalize_palette(palette)

    @model_validator(mode="after")
    def validate_knight_canvas(self) -> "SpriteRequest":
        if self.template == "knight" and min(self.width, self.height) < 32:
            raise ValueError("Knight canvas must be at least 32 pixels in each dimension")
        return self


class Pivot(Model):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class Manifest(Model):
    schema_version: Literal["1.0"] = "1.0"
    asset_id: AssetId
    type: Annotated[str, Field(pattern=r"^[a-z][a-z_]{0,31}$")] = "icon"
    style: Literal["pixel_art"] = "pixel_art"
    template: Literal["heart", "knight", "agent", "imported"] = "heart"
    description: str = Field(min_length=1, max_length=4000)
    canvas: Canvas
    palette: Palette
    transparent: bool = True
    pivot: Pivot
    profile_id: ProfileId | None = None
    frames: list[Literal["sprite.png"]] = Field(
        default_factory=lambda: ["sprite.png"],
        min_length=1,
        max_length=1,
    )
    source_sha256: Digest
    technical_status: Literal["passed"] = "passed"
    art_review_status: Literal["pending", "agent_responsibility"] = "agent_responsibility"
    approval_source: Literal["automated_technical_checks"] | None = "automated_technical_checks"
    history: list[str] = Field(default_factory=list)
    parent_asset_id: AssetId | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    _normalize_palette = field_validator("palette")(normalize_palette)

    @model_validator(mode="after")
    def validate_pivot(self) -> "Manifest":
        if self.pivot.x >= self.canvas.width or self.pivot.y >= self.canvas.height:
            raise ValueError("pivot must be inside the canvas")
        return self


class ValidationReport(Model):
    asset_id: AssetId | AnimationId
    technical_status: Literal["passed", "failed"]
    art_review_status: Literal["agent_responsibility"] = "agent_responsibility"
    approval_source: Literal["automated_technical_checks"] | None = None
    status: Literal["ready_for_export", "failed"]
    errors: list[str]
    warnings: list[str] = Field(
        default_factory=lambda: [
            "Technical readiness is automated. "
            "Artistic craftsmanship belongs to the authoring agent.",
        ]
    )


class SpriteResult(Model):
    asset_id: AssetId
    png_path: LocalPath
    manifest_path: LocalPath
    status: Literal["ready_for_export"] = "ready_for_export"
    validation: ValidationReport


class AnimationRequest(Model):
    asset_id: AssetId
    motion: Literal["idle", "attack"]
    duration_ms: Duration = 120


class FrameRect(Model):
    x: int = Field(ge=0, le=4096)
    y: Literal[0] = 0
    width: Size
    height: Size


class AnimationFrame(Model):
    file: Annotated[str, Field(pattern=r"^[0-9]{3}\.png$")]
    duration_ms: Duration
    rect: FrameRect
    source_sha256: Digest
    source_asset_id: AssetId | None = None


class AnimationManifest(Model):
    schema_version: Literal["1.0"] = "1.0"
    animation_id: AnimationId
    type: Literal["animation"] = "animation"
    source_asset_id: AssetId
    source_sha256: Digest
    motion: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    motion_plan: Literal["knight_v1", "agent_frames"] = "knight_v1"
    loop: bool
    canvas: Canvas
    palette: Palette
    transparent: bool = True
    pivot: Pivot
    frames: list[AnimationFrame] = Field(min_length=1, max_length=16)
    allow_duplicate_frames: bool = False
    spritesheet: Literal["spritesheet.png"] = "spritesheet.png"
    preview: Literal["preview.gif"] = "preview.gif"
    spritesheet_sha256: Digest
    preview_sha256: Digest
    technical_status: Literal["passed"] = "passed"
    art_review_status: Literal["pending", "agent_responsibility"] = "agent_responsibility"
    approval_source: Literal["automated_technical_checks"] | None = "automated_technical_checks"

    _normalize_palette = field_validator("palette")(normalize_palette)

    @model_validator(mode="after")
    def validate_layout(self) -> "AnimationManifest":
        if self.motion_plan == "knight_v1":
            count = 4 if self.motion == "idle" else 6
            if (
                self.motion not in ("idle", "attack")
                or len(self.frames) != count
                or self.loop != (self.motion == "idle")
            ):
                raise ValueError("Frame count and loop flag must match the motion plan")
        if self.pivot.x >= self.canvas.width or self.pivot.y >= self.canvas.height:
            raise ValueError("Animation pivot must be inside the canvas")
        for i, frame in enumerate(self.frames):
            expected = FrameRect(
                x=i * self.canvas.width, width=self.canvas.width, height=self.canvas.height
            )
            if frame.file != f"{i:03}.png" or frame.rect != expected:
                raise ValueError("Frame names and rectangles must match the ordered strip")
        return self


class AnimationResult(Model):
    animation_id: AnimationId
    source_asset_id: AssetId
    motion: str
    frame_count: int
    frame_paths: list[LocalPath]
    manifest_path: LocalPath
    spritesheet_path: LocalPath
    preview_path: LocalPath
    status: Literal["ready_for_export"] = "ready_for_export"
    validation: ValidationReport


class FrameAnimationRequest(Model):
    asset_id: AssetId
    frame_asset_ids: list[AssetId] = Field(min_length=1, max_length=16)
    durations_ms: list[Duration] = Field(min_length=1, max_length=16)
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    loop: bool = True
    allow_duplicate_frames: bool = False

    @model_validator(mode="after")
    def validate_timing(self) -> "FrameAnimationRequest":
        if len(self.frame_asset_ids) != len(self.durations_ms):
            raise ValueError("Every frame must have one duration")
        return self
