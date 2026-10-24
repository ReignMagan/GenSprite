"""Agent-authored UI-kit concepts, durable generation, and portable component crops."""

import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from mcp.server.fastmcp import Context, FastMCP
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .assets import AssetStore
from .drawing import PixelDrawing
from .image_ops import auto_slice_asset, edit_sprite
from .jobs import JobManager
from .models import AssetId, Canvas, Digest, Size
from .production import Production, Wait

KitId = Annotated[str, Field(pattern=r"^u_[0-9a-f]{32}$")]
Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
MAX_JSON = 65536


class _Model(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)


class _Border(_Model):
    left: int = Field(ge=0, le=255)
    right: int = Field(ge=0, le=255)
    top: int = Field(ge=0, le=255)
    bottom: int = Field(ge=0, le=255)


class _Component(_Model):
    name: Name
    source_asset_id: AssetId
    x: int = Field(ge=0, le=255)
    y: int = Field(ge=0, le=255)
    width: int = Field(alias="w", ge=1, le=256)
    height: int = Field(alias="h", ge=1, le=256)
    border: _Border | None = None

    @model_validator(mode="after")
    def borders_fit(self) -> "_Component":
        if self.border and (self.border.left + self.border.right >= self.width
                            or self.border.top + self.border.bottom >= self.height):
            raise ValueError("Nine-patch borders must leave a nonempty center")
        return self


class _Job(_Model):
    job_id: Annotated[str, Field(pattern=r"^j_[0-9a-f]{32}$")]
    kind: Literal["concept", "sheet"]
    status: Literal["queued", "running", "completed", "failed", "cancelled"] = "queued"
    asset_ids: list[AssetId] = Field(default_factory=list, max_length=4)
    error: str | None = Field(default=None, max_length=256)


class _Kit(_Model):
    ui_kit_id: KitId
    name: str = Field(min_length=1, max_length=100)
    instructions: str = Field(default="", max_length=3000)
    status: Literal[
        "draft", "generating", "concepts_ready", "concept_selected", "sheets_ready",
        "components_ready", "generation_failed", "finalized", "cancelled",
    ] = "draft"
    concepts: list[AssetId] = Field(default_factory=list, max_length=16)
    selected_concept_asset_id: AssetId | None = None
    component_sheets: list[AssetId] = Field(default_factory=list, max_length=16)
    jobs: list[_Job] = Field(default_factory=list, max_length=32)
    components: list[_Component] = Field(default_factory=list, max_length=64)
    cropped_assets: dict[Name, AssetId] = Field(default_factory=dict)
    placeholder_labels: bool = False
    quality_summary: dict[str, Any] = Field(default_factory=dict)
    finalized_manifest_sha256: Digest | None = None


_COMPONENTS = TypeAdapter(Annotated[list[_Component], Field(min_length=1, max_length=64)])


class UIKits:
    def __init__(self, store: AssetStore, production: Production, jobs: JobManager):
        self.store, self.production, self.jobs = store, production, jobs

    def _path(self, ui_kit_id: str, *parts: str) -> Path:
        if not isinstance(ui_kit_id, str) or not re.fullmatch(r"u_[0-9a-f]{32}", ui_kit_id):
            raise ValueError("Invalid UI-kit ID; use its generated u_ ID")
        path = self.store.root / "ui_kits" / ui_kit_id
        path = path.joinpath(*parts)
        if not path.resolve().is_relative_to(self.store.root):
            raise ValueError("UI-kit path escapes the configured store")
        for part in [path, *path.parents]:
            if part == self.store.root:
                break
            if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                raise ValueError("Symlinks are not allowed in UI-kit paths")
        return path

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            if path.stat().st_size > MAX_JSON:
                raise ValueError("UI-kit JSON exceeds the 64 KiB limit")
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read UI-kit JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("UI-kit JSON must be an object")
        return data

    @staticmethod
    def _encoded(data: dict) -> bytes:
        raw = json.dumps(data, indent=2, allow_nan=False).encode("utf-8")
        if len(raw) > MAX_JSON:
            raise ValueError("UI-kit JSON exceeds the 64 KiB limit")
        return raw

    def _save(self, kit: _Kit) -> None:
        raw = self._encoded(kit.model_dump())
        path = self._path(kit.ui_kit_id, "kit.json")
        temporary = self._path(kit.ui_kit_id, f"{uuid4().hex}.tmp")
        with temporary.open("xb") as output:
            output.write(raw)
        temporary.replace(path)

    def _asset(self, asset_id: str):
        asset_id = TypeAdapter(AssetId).validate_python(asset_id, strict=True)
        manifest = self.store._manifest(asset_id)
        if self.store.validate_sprite(asset_id)["errors"]:
            raise ValueError("UI-kit asset failed technical validation")
        return manifest

    @staticmethod
    def _mutable(kit: _Kit) -> None:
        if kit.status in ("cancelled", "finalized"):
            raise ValueError(f"UI kit is {kit.status}; create a new kit for further changes")

    @staticmethod
    def _status(kit: _Kit) -> None:
        if kit.status in ("cancelled", "finalized"):
            return
        if any(job.status in ("queued", "running") for job in kit.jobs):
            kit.status = "generating"
        elif kit.components:
            kit.status = "components_ready"
        elif kit.component_sheets:
            kit.status = "sheets_ready"
        elif kit.selected_concept_asset_id:
            kit.status = "concept_selected"
        elif kit.concepts:
            kit.status = "concepts_ready"
        elif any(job.status == "failed" for job in kit.jobs):
            kit.status = "generation_failed"
        else:
            kit.status = "draft"

    def _get(self, ui_kit_id: str) -> _Kit:
        kit = _Kit.model_validate(self._read_json(self._path(ui_kit_id, "kit.json")))
        if kit.ui_kit_id != ui_kit_id:
            raise ValueError("UI-kit ID does not match its directory")
        changed = False
        for job in kit.jobs:
            if job.status not in ("queued", "running"):
                continue
            data = self.jobs.get(job.job_id)
            job.status = data["status"]
            job.error = str(data["error"])[:256] if data.get("error") is not None else None
            if job.status == "completed":
                assets = (data.get("output") or {}).get("assets")
                if not isinstance(assets, list) or not 1 <= len(assets) <= 4:
                    raise ValueError("UI-kit job completed without bounded artwork assets")
                for result in assets:
                    asset_id = result.get("asset_id") if isinstance(result, dict) else None
                    manifest = self._asset(asset_id)
                    if manifest.metadata.get("ui_kit_id") != kit.ui_kit_id:
                        raise ValueError("Generation output does not belong to this UI kit")
                    job.asset_ids.append(asset_id)
                destination = kit.concepts if job.kind == "concept" else kit.component_sheets
                destination.extend(
                    asset_id for asset_id in job.asset_ids if asset_id not in destination
                )
            changed = True
        self._status(kit)
        if changed:
            self._save(kit)
        return kit

    def create_ui_kit(
        self, name: str, instructions: str = "", concept_asset_id: str | None = None,
    ) -> dict:
        kit = _Kit(ui_kit_id=f"u_{uuid4().hex}", name=name, instructions=instructions)
        if concept_asset_id is not None:
            self._asset(concept_asset_id)
            kit.concepts = [concept_asset_id]
            kit.selected_concept_asset_id = concept_asset_id
            kit.status = "concept_selected"
        self._encoded(kit.model_dump())
        self._path(kit.ui_kit_id).mkdir(parents=True, exist_ok=False)
        self._save(kit)
        return kit.model_dump()

    def get_ui_kit(self, ui_kit_id: str) -> dict:
        return self._get(ui_kit_id).model_dump()

    def list_ui_kits(self, limit: int = 50) -> dict:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        root = self._path("u_" + "0" * 32).parent
        kits = []
        if root.exists():
            for directory in root.iterdir():
                if re.fullmatch(r"u_[0-9a-f]{32}", directory.name):
                    kit = self._get(directory.name)
                    kits.append({"ui_kit_id": kit.ui_kit_id, "name": kit.name,
                                 "status": kit.status, "component_count": len(kit.components)})
                    if len(kits) == limit:
                        break
        return {"ui_kits": kits}

    async def _generate(
        self, ui_kit_id: str, ctx: Context | None, kind: Literal["concept", "sheet"],
        drawings: list[dict] | None, width: int, height: int, count: int, wait_seconds: int,
    ) -> dict:
        kit = self._get(ui_kit_id)
        self._mutable(kit)
        Canvas(width=width, height=height)
        if type(count) is not int or not 1 <= count <= 4:
            raise ValueError("count must be an integer from 1 to 4")
        if type(wait_seconds) is not int or not 0 <= wait_seconds <= 30:
            raise ValueError("wait_seconds must be an integer from 0 to 30")
        if kind == "sheet" and kit.selected_concept_asset_id is None:
            raise ValueError("Select a concept before generating component sheets")
        if drawings is not None:
            if not isinstance(drawings, list) or not 1 <= len(drawings) <= 4:
                raise ValueError("Supply 1..4 agent drawings")
            for drawing in drawings:
                if PixelDrawing.model_validate(drawing).image().size != (width, height):
                    raise ValueError("Drawing dimensions differ from the requested canvas")
            count = len(drawings)
        owned = kit.concepts if kind == "concept" else kit.component_sheets
        reserved = sum(1 for job in kit.jobs
                       if job.kind == kind and job.status in ("queued", "running"))
        if len(kit.jobs) + count > 32 or len(owned) + reserved + count > 16:
            raise ValueError("UI-kit generation limit reached (16 assets per stage, 32 jobs)")
        reference = kit.selected_concept_asset_id if kind == "sheet" else None
        prompt = (
            f"UI kit {kit.name}. {kit.instructions}\n"
            + ("Design a coherent UI concept." if kind == "concept" else
               "Draw the UI component sheet using the selected concept's palette and design. "
               "Separate components clearly. The authoring agent owns design and component labels.")
        )
        submitted_ids = []
        for index in range(count):
            result = await self.production.generate(
                prompt, ctx, width=width, height=height,
                drawing=drawings[index] if drawings is not None else None,
                reference_asset_id=reference, mode="ui", wait_seconds=0,
                metadata={"ui_kit_id": ui_kit_id, "ui_kit_stage": kind},
            )
            kit = self._get(ui_kit_id)
            if kit.status == "finalized":
                self.jobs.cancel(result["job_id"])
                raise ValueError("UI kit finalized while generation was being submitted")
            record = _Job(job_id=result["job_id"], kind=kind)
            kit.jobs.append(record)
            submitted_ids.append(record.job_id)
            if kit.status == "cancelled":
                record.status = self.jobs.cancel(record.job_id)["status"]
            self._status(kit)
            self._save(kit)
            if kit.status == "cancelled":
                return kit.model_dump()
        for job_id in submitted_ids:
            await self.jobs.check(job_id, wait_seconds)
        return self.get_ui_kit(ui_kit_id)

    async def generate_ui_kit_concepts(
        self, ui_kit_id: str, ctx: Context | None, drawings: list[dict] | None = None,
        width: int = 32, height: int = 32, count: int = 1, wait_seconds: int = 0,
    ) -> dict:
        return await self._generate(ui_kit_id, ctx, "concept", drawings,
                                    width, height, count, wait_seconds)

    def select_ui_kit_concept(self, ui_kit_id: str, concept_asset_id: str) -> dict:
        kit = self._get(ui_kit_id)
        self._mutable(kit)
        if concept_asset_id not in kit.concepts:
            raise ValueError("Selected concept must be an owned concept in this UI kit")
        self._asset(concept_asset_id)
        if concept_asset_id != kit.selected_concept_asset_id and (
            kit.component_sheets or any(job.kind == "sheet" for job in kit.jobs)
        ):
            raise ValueError("Start a new UI kit to change concept after sheet generation")
        kit.selected_concept_asset_id = concept_asset_id
        self._status(kit)
        self._save(kit)
        return kit.model_dump()

    async def generate_ui_kit_component_sheets(
        self, ui_kit_id: str, ctx: Context | None, drawings: list[dict] | None = None,
        width: int = 32, height: int = 32, count: int = 1, wait_seconds: int = 0,
    ) -> dict:
        return await self._generate(ui_kit_id, ctx, "sheet", drawings,
                                    width, height, count, wait_seconds)

    def _quality(self, kit: _Kit) -> dict:
        issues = []
        for index, component in enumerate(kit.components):
            manifest = self._asset(component.source_asset_id)
            if component.x + component.width > manifest.canvas.width or (
                component.y + component.height > manifest.canvas.height
            ):
                raise ValueError("Component rectangle exceeds its source canvas")
            path = self.store._path("generated", component.source_asset_id, "sprite.png")
            with Image.open(path) as image:
                alpha = image.getchannel("A").crop((
                    component.x, component.y, component.x + component.width,
                    component.y + component.height,
                ))
                if alpha.getbbox() is None:
                    issues.append({"code": "empty_component", "component": component.name,
                                   "severity": "error"})
            for other in kit.components[:index]:
                if component.source_asset_id == other.source_asset_id and (
                    component.x < other.x + other.width and other.x < component.x + component.width
                    and component.y < other.y + other.height
                    and other.y < component.y + component.height
                ):
                    issues.append({"code": "overlapping_components", "component": component.name,
                                   "other": other.name, "severity": "warning"})
        errors = [issue for issue in issues if issue["severity"] == "error"]
        warnings = [issue for issue in issues if issue["severity"] == "warning"]
        reported = errors + warnings[:64 - len(errors)]
        return {
            "technical_status": "failed" if errors else "passed",
            "issues": reported, "omitted_issue_count": len(issues) - len(reported),
            "component_count": len(kit.components),
            "labels": "placeholder" if kit.placeholder_labels else "agent_supplied",
            "artistic_quality": "authoring_agent_responsibility",
        }

    def extract_ui_kit_components(
        self, ui_kit_id: str, components: list[dict] | None = None,
    ) -> dict:
        kit = self._get(ui_kit_id)
        self._mutable(kit)
        sources = set(kit.component_sheets)
        if kit.selected_concept_asset_id:
            sources.add(kit.selected_concept_asset_id)
        if not sources:
            raise ValueError("Generate component sheets or supply an initial concept first")
        cropped = {}
        if components is not None:
            parsed = _COMPONENTS.validate_python(components, strict=True)
            if any(min(component.width, component.height) < 8 for component in parsed):
                raise ValueError(
                    "Explicit rectangles must be at least 8x8; automatic slices pad small art"
                )
            if any(component.source_asset_id not in sources for component in parsed):
                raise ValueError(
                    "Component source must belong to this kit's selected concept or sheets"
                )
            if len({component.name for component in parsed}) != len(parsed):
                raise ValueError("Component names must be distinct")
        else:
            parsed = []
            for source_id in kit.component_sheets or [kit.selected_concept_asset_id]:
                result = auto_slice_asset(self.store, source_id, max_slices=64 - len(parsed))
                for item in result["slices"]:
                    rect = item["rect"]
                    name = f"component_{len(parsed) + 1:02}"
                    parsed.append(_Component(name=name, source_asset_id=source_id, **rect))
                    cropped[name] = item["asset_id"]
                if len(parsed) == 64 and source_id != (kit.component_sheets or [source_id])[-1]:
                    raise ValueError("UI kit contains more than 64 components")
        kit.components, kit.cropped_assets = parsed, cropped
        kit.placeholder_labels = components is None
        kit.quality_summary = self._quality(kit)
        self._status(kit)
        self._save(kit)
        return kit.model_dump()

    def _finalized(self, kit: _Kit) -> dict:
        path = self._path(kit.ui_kit_id, "manifest.json")
        manifest = self._read_json(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != kit.finalized_manifest_sha256:
            raise ValueError("Finalized UI-kit manifest integrity changed")
        for component in manifest["components"]:
            filename = f"components/{component['name']}.png"
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", component["name"]):
                raise ValueError("Invalid portable component name")
            png = self._path(kit.ui_kit_id, filename)
            if png.stat().st_size > 4 * 1024 * 1024 or (
                hashlib.sha256(png.read_bytes()).hexdigest() != component["source_sha256"]
            ):
                raise ValueError("Finalized component PNG integrity changed")
        return {**kit.model_dump(), "manifest_path": path, "components": manifest["components"]}

    def finalize_ui_kit(self, ui_kit_id: str) -> dict:
        kit = self._get(ui_kit_id)
        if kit.status == "finalized":
            return self._finalized(kit)
        self._mutable(kit)
        if not kit.selected_concept_asset_id or not kit.components:
            raise ValueError("Select a concept and extract components before finalizing")
        if any(job.status in ("queued", "running") for job in kit.jobs):
            raise ValueError("Wait for generation jobs before finalizing the UI kit")
        kit.quality_summary = self._quality(kit)
        if kit.quality_summary["technical_status"] != "passed":
            raise ValueError(
                "Component geometry contains empty components; correct extraction first"
            )
        portable = []
        self._path(ui_kit_id, "components").mkdir(exist_ok=True)
        for component in kit.components:
            asset_id = kit.cropped_assets.get(component.name)
            if asset_id is None:
                result = edit_sprite(self.store, component.source_asset_id, [{
                    "op": "crop", "x": component.x, "y": component.y,
                    "width": component.width, "height": component.height,
                }])
                asset_id = result["asset_id"]
                kit.cropped_assets[component.name] = asset_id
                self._save(kit)
            manifest = self._asset(asset_id)
            raw = self.store._path("generated", asset_id, "sprite.png").read_bytes()
            destination = self._path(ui_kit_id, "components", f"{component.name}.png")
            if destination.exists():
                if destination.stat().st_size > 4 * 1024 * 1024 or destination.read_bytes() != raw:
                    raise ValueError("Existing component PNG differs; refusing to overwrite")
            else:
                with destination.open("xb") as output:
                    output.write(raw)
            portable.append({
                **component.model_dump(), "asset_id": asset_id,
                "file": f"components/{component.name}.png", "canvas": manifest.canvas.model_dump(),
                "source_sha256": manifest.source_sha256,
            })
        contract = {
            "schema_version": "1.0", "ui_kit_id": ui_kit_id, "name": kit.name,
            "instructions": kit.instructions, "concept_asset_id": kit.selected_concept_asset_id,
            "components": portable, "quality_summary": kit.quality_summary,
        }
        path = self._path(ui_kit_id, "manifest.json")
        raw = self._encoded(contract)
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError("Existing UI-kit manifest differs; refusing to overwrite")
        else:
            with path.open("xb") as output:
                output.write(raw)
        kit.finalized_manifest_sha256 = hashlib.sha256(raw).hexdigest()
        kit.status = "finalized"
        self._save(kit)
        return self._finalized(kit)

    def cancel_ui_kit(self, ui_kit_id: str) -> dict:
        kit = self._get(ui_kit_id)
        if kit.status == "finalized":
            raise ValueError("Finalized UI kit cannot be cancelled")
        for job in kit.jobs:
            if job.status in ("queued", "running"):
                job.status = self.jobs.cancel(job.job_id)["status"]
        kit.status = "cancelled"
        self._save(kit)
        return kit.model_dump()


def register_ui_kit_tools(
    server: FastMCP, store: AssetStore, production: Production, jobs: JobManager,
) -> UIKits:
    kits = UIKits(store, production, jobs)

    @server.tool()
    def create_ui_kit(
        name: str, instructions: str = "", concept_asset_id: str | None = None,
    ) -> dict:
        """Create a durable local UI kit. Optional real concept asset is selected immediately."""
        return kits.create_ui_kit(name, instructions, concept_asset_id)

    @server.tool()
    def get_ui_kit(ui_kit_id: str) -> dict:
        """Poll saved generation jobs and return this kit's actual assets and current state."""
        return kits.get_ui_kit(ui_kit_id)

    @server.tool()
    def list_ui_kits(limit: int = 50) -> dict:
        """List up to 100 locally saved UI kits and their current production state."""
        return kits.list_ui_kits(limit)

    @server.tool()
    async def generate_ui_kit_concepts(
        ui_kit_id: str, ctx: Context, drawings: list[dict[str, Any]] | None = None,
        width: Size = 32, height: Size = 32, count: int = 1, wait_seconds: Wait = 0,
    ) -> dict:
        """Submit 1..4 real agent concept drawings {rows,palette}, or request optional sampling.
        Supplied drawings determine count. Poll get_ui_kit or the returned durable job IDs.
        """
        return await kits.generate_ui_kit_concepts(
            ui_kit_id, ctx, drawings, width, height, count, wait_seconds,
        )

    @server.tool()
    def select_ui_kit_concept(ui_kit_id: str, concept_asset_id: str) -> dict:
        """Select a valid concept owned by this kit before component-sheet generation."""
        return kits.select_ui_kit_concept(ui_kit_id, concept_asset_id)

    @server.tool()
    async def generate_ui_kit_component_sheets(
        ui_kit_id: str, ctx: Context, drawings: list[dict[str, Any]] | None = None,
        width: Size = 32, height: Size = 32, count: int = 1, wait_seconds: Wait = 0,
    ) -> dict:
        """Submit real component sheets using the selected concept as agent reference.
        Supply 1..4 drawings {rows,palette}, or use a client supporting optional sampling.
        """
        return await kits.generate_ui_kit_component_sheets(
            ui_kit_id, ctx, drawings, width, height, count, wait_seconds,
        )

    @server.tool()
    def extract_ui_kit_components(ui_kit_id: str, components: list[dict] | None = None) -> dict:
        """Set <=64 named rectangles {name,source_asset_id,x,y,width,height,border?}.
        Explicit rectangles >=8px; border={left,right,top,bottom} preserves a nine-patch center.
        Omit components for real alpha-component slicing with honest placeholder labels.
        """
        return kits.extract_ui_kit_components(ui_kit_id, components)

    @server.tool()
    def finalize_ui_kit(ui_kit_id: str) -> dict:
        """Create/reuse actual component crops and a portable manifest plus PNG directory.
        Automated geometry/integrity checks apply; design and labels belong to the agent.
        """
        return kits.finalize_ui_kit(ui_kit_id)

    @server.tool()
    def cancel_ui_kit(ui_kit_id: str) -> dict:
        """Cancel outstanding kit jobs, preserving already-written immutable assets."""
        return kits.cancel_ui_kit(ui_kit_id)

    return kits
