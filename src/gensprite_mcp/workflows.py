"""Guided character, atlas and local-upload workflows around actual asset jobs."""

import json
import re
import time
from typing import Annotated, Any
from uuid import uuid4

from mcp.server.fastmcp import Context, FastMCP
from PIL import Image
from pydantic import Field

from .assets import AssetStore
from .image_ops import import_image
from .jobs import JobManager
from .models import Canvas, Size
from .production import Count, Production, Wait


class Workflows:
    def __init__(self, store: AssetStore, production: Production, jobs: JobManager):
        self.store, self.production, self.jobs = store, production, jobs
        self.submitting: set[str] = set()

    def _write(self, kind: str, identifier: str, record: dict) -> None:
        raw = json.dumps(record, default=str)
        if len(raw.encode("utf-8")) > 65536:
            raise ValueError("Workflow record exceeds 64 KiB")
        path = self.store._path(kind, identifier, "record.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.store._path(kind, identifier, f"{uuid4().hex}.tmp")
        with temporary.open("x", encoding="utf-8") as output:
            output.write(raw)
        temporary.replace(path)

    def _read(self, kind: str, identifier: str) -> dict:
        path = self.store._path(kind, identifier, "record.json")
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("Workflow not found or record too large")
        return json.loads(path.read_text(encoding="utf-8"))

    async def character_run(
        self,
        character_id: str,
        perspective: str,
        ctx: Context | None,
        animation_ids: list[str] | None = None,
        custom_animations: list[dict] | None = None,
        frame_asset_ids: dict[str, list[str]] | None = None,
        frames: dict[str, list[dict]] | None = None,
    ) -> dict:
        if perspective not in ("platformer", "topdown", "isometric"):
            raise ValueError("perspective must be platformer, topdown or isometric")
        if self.store.validate_sprite(character_id)["errors"]:
            raise ValueError("Character source validation failed")
        names = animation_ids if animation_ids is not None else ["idle", "attack"]
        custom = custom_animations or []
        if not 1 <= len(names) + len(custom) <= 8:
            raise ValueError("Character runs require 1..8 motions")
        specs = [{"id": name, "prompt": name} for name in names] + custom
        identifiers = [
            spec.get("id") or spec.get("label", "").lower().replace(" ", "_") for spec in specs
        ]
        if len(set(identifiers)) != len(identifiers) or any(
            not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name)
            for name in identifiers
        ):
            raise ValueError("Motion IDs must be distinct lowercase names")
        run_id = f"r_{uuid4().hex}"
        record = {
            "run_id": run_id,
            "character_id": character_id,
            "perspective": perspective,
            "jobs": [],
            "status": "running",
            "requested_motions": identifiers,
            "submission_complete": False,
        }
        self._write("runs", run_id, record)
        self.submitting.add(run_id)
        try:
            for name, spec in zip(identifiers, specs, strict=True):
                job = await self.production.animate(
                    character_id,
                    spec.get("prompt", name),
                    ctx,
                    frame_asset_ids=(frame_asset_ids or {}).get(name),
                    frames=(frames or {}).get(name),
                    output_frames=spec.get("output_frames"),
                    perspective=perspective,
                )
                record["jobs"].append({"animation_id": name, "job_id": job["job_id"]})
                self._write("runs", run_id, record)
            record["submission_complete"] = True
            self._write("runs", run_id, record)
        except Exception as exc:
            record.update(status="failed", error=str(exc)[:1000])
            self._write("runs", run_id, record)
            raise
        finally:
            self.submitting.discard(run_id)
        return {
            **record,
            "operation_id": run_id,
            "poll": {"tool": "check_character_animation_run", "arguments": {"run_id": run_id}},
        }

    def check_character_run(self, run_id: str) -> dict:
        record = self._read("runs", run_id)
        items = [self.jobs.get(item["job_id"]) for item in record["jobs"]]
        assets = [item["output"] for item in items if item["status"] == "completed"]
        statuses = {item["status"] for item in items}
        if not record.get("submission_complete"):
            if run_id not in self.submitting:
                record.update(status="failed", error="Character run submission was interrupted")
                self._write("runs", run_id, record)
        elif record["status"] != "failed":
            record["status"] = (
                "failed"
                if "failed" in statuses
                else "cancelled"
                if "cancelled" in statuses
                else "completed"
                if items and statuses == {"completed"}
                else "running"
            )
        return {**record, "items": items, "assets": assets}

    def create_upload(self, file_name: str, size_bytes: int) -> dict:
        if (
            not isinstance(file_name, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}\.png", file_name)
            or type(size_bytes) is not int
            or not 1 <= size_bytes <= 4 * 1024 * 1024
        ):
            raise ValueError("Uploads require a simple PNG filename and 1..4 MiB declared size")
        upload_id = f"t_{uuid4().hex}"
        path = self.store._path("uploads", upload_id, "payload.png")
        record = {
            "upload_id": upload_id,
            "file_name": file_name,
            "size_bytes": size_bytes,
            "expires_at": time.time() + 600,
            "status": "awaiting_bytes",
        }
        self._write("uploads", upload_id, record)
        return {
            **record,
            "upload_url": path.as_uri(),
            "upload_path": str(path),
            "method": "local_file_write",
            "note": "Write bytes locally, then finalize; no HTTP PUT",
        }

    def finalize_upload(self, upload_id: str, display_name: str = "Uploaded sprite") -> dict:
        record = self._read("uploads", upload_id)
        if record["status"] == "completed":
            result = record["output"]
            if self.store.validate_sprite(result["asset_id"])["errors"]:
                raise ValueError("Previously imported upload asset failed validation")
            return result
        if time.time() > record["expires_at"]:
            raise ValueError("Upload expired; create a new upload slot")
        if type(record["size_bytes"]) is not int or not 1 <= record["size_bytes"] <= 4194304:
            raise ValueError("Upload record size must be1..4 MiB")
        path = self.store._path("uploads", upload_id, "payload.png")
        if not path.is_file() or path.stat().st_size != record["size_bytes"]:
            raise ValueError("Upload payload is missing or size differs from the declared PNG")
        import base64

        result = import_image(
            self.store, base64.b64encode(path.read_bytes()).decode(), display_name
        )
        record.update(status="completed", output=result)
        self._write("uploads", upload_id, record)
        return result

    def report_integration_error(
        self,
        error_message: str,
        engine: str | None = None,
        asset_id: str | None = None,
        details: dict | None = None,
    ) -> dict:
        if not isinstance(error_message, str) or not 1 <= len(error_message) <= 8000:
            raise ValueError("error_message must contain 1..8000 characters")
        if engine is not None and (not isinstance(engine, str) or not 1 <= len(engine) <= 80):
            raise ValueError("engine must contain 1..80 characters")
        if asset_id:
            report = (
                self.store.validate_animation(asset_id)
                if asset_id.startswith("n_")
                else self.store.validate_sprite(asset_id)
            )
            if report["errors"]:
                raise ValueError("Reported asset validation failed")
        identifier = f"i_{uuid4().hex}"
        record = {
            "report_id": identifier,
            "status": "recorded",
            "created_at": time.time(),
            "error_message": error_message,
            "engine": engine,
            "asset_id": asset_id,
            "details": details or {},
        }
        self._write("reports", identifier, record)
        return {
            **record,
            "report_url": self.store._path("reports", identifier, "record.json").as_uri(),
            "delivery": "local_only",
        }

    async def tileset(
        self,
        prompt: str,
        ctx: Context | None,
        *,
        tile_size: int = 16,
        columns: int = 4,
        rows: int = 4,
        piece_set: str = "atlas",
        tile_asset_ids: list[str] | None = None,
        drawing: dict | None = None,
        wait_seconds: int = 0,
    ) -> dict:
        if tile_size not in (8, 16, 32, 64) or type(tile_size) is not int:
            raise ValueError("tile_size must be 8,16,32 or64")
        if drawing is not None and tile_asset_ids is not None:
            raise ValueError("Supply a drawing or tile asset IDs, not both")
        if type(columns) is not int or type(rows) is not int or min(columns, rows) < 1:
            raise ValueError("Atlas rows and columns must be positive integers")
        Canvas(width=tile_size * columns, height=tile_size * rows)
        if piece_set not in ("atlas", "topdown-15"):
            raise ValueError("piece_set must be atlas or topdown-15")
        count = 15 if piece_set == "topdown-15" else len(tile_asset_ids or []) or columns * rows
        if count > columns * rows or (piece_set == "topdown-15" and (columns, rows) != (4, 4)):
            raise ValueError("Piece count does not fit the selected atlas layout")
        metadata = {
            "tileset": {
                "tile_width": tile_size,
                "tile_height": tile_size,
                "columns": columns,
                "rows": rows,
                "tile_count": count,
                "piece_set": piece_set,
            }
        }
        if not tile_asset_ids:
            return await self.production.generate(
                f"{prompt}. Draw a {columns}x{rows} tile atlas, {tile_size}px per tile; "
                f"{count} populated tiles in row-major order.",
                ctx,
                width=tile_size * columns,
                height=tile_size * rows,
                drawing=drawing,
                mode="tileset",
                metadata=metadata,
                wait_seconds=wait_seconds,
            )
        if len(tile_asset_ids) != count or len(tile_asset_ids) > 64:
            raise ValueError("Supply exactly the atlas tile count, at most64")
        images = []
        palette = []
        for asset_id in tile_asset_ids:
            manifest = self.store._manifest(asset_id)
            if self.store.validate_sprite(asset_id)["errors"]:
                raise ValueError("Tile source validation failed")
            if (manifest.canvas.width, manifest.canvas.height) != (tile_size, tile_size):
                raise ValueError("Tile canvas differs from tile_size")
            palette.extend(color for color in manifest.palette if color not in palette)
            with Image.open(self.store._path("generated", asset_id, "sprite.png")) as image:
                images.append(image.copy())
        if len(palette) > 32:
            raise ValueError("Tile sources exceed the shared32-color palette limit")

        def work() -> dict:
            atlas = Image.new("RGBA", (columns * tile_size, rows * tile_size))
            for index, image in enumerate(images):
                atlas.paste(image, (index % columns * tile_size, index // columns * tile_size))
            saved = self.store.save_image(
                atlas,
                prompt,
                palette,
                asset_type="tileset",
                metadata={**metadata, "tile_sources": tile_asset_ids},
            )
            return {"assets": [saved]}

        submitted = self.jobs.submit("generate_tileset", work)
        return (
            await self.jobs.check(submitted["job_id"], wait_seconds) if wait_seconds else submitted
        )


def register_workflow_tools(
    server: FastMCP,
    store: AssetStore,
    production: Production,
    jobs: JobManager,
) -> Workflows:
    workflows = Workflows(store, production, jobs)

    @server.tool()
    def list_character_workflows() -> dict[str, Any]:
        """List agent-authored perspective/motion contracts and deterministic native motions."""
        return {
            "perspectives": ["platformer", "topdown", "isometric"],
            "agent_motions": ["idle", "walk", "run", "attack", "hurt", "death"],
            "native_knight_motions": ["idle", "attack"],
            "note": "Other motions require agent-supplied frame artwork or client sampling.",
        }

    @server.tool()
    async def generate_character(
        prompt: str,
        perspective: str,
        ctx: Context,
        drawing: dict[str, Any] | None = None,
        image: str | None = None,
        width: Size = 32,
        height: Size = 32,
        wait_seconds: Wait = 0,
    ) -> dict[str, Any]:
        """Create one canonical character through the agent's artwork and retain its perspective."""
        if perspective not in ("platformer", "topdown", "isometric"):
            raise ValueError("Unsupported perspective")
        return await production.generate(
            prompt,
            ctx,
            width=width,
            height=height,
            drawing=drawing,
            image=image,
            metadata={"perspective": perspective},
            wait_seconds=wait_seconds,
        )

    @server.tool()
    async def generate_character_animations(
        character_id: str,
        perspective: str,
        ctx: Context,
        animation_ids: list[str] | None = None,
        custom_animations: list[dict[str, Any]] | None = None,
        frame_asset_ids: dict[str, list[str]] | None = None,
        frames: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Enqueue preset/custom motions for the same source; poll the returned run ID."""
        return await workflows.character_run(
            character_id,
            perspective,
            ctx,
            animation_ids,
            custom_animations,
            frame_asset_ids,
            frames,
        )

    @server.tool()
    def check_character_animation_run(run_id: str) -> dict[str, Any]:
        """Recover actual per-motion job states and generated animation outputs."""
        return workflows.check_character_run(run_id)

    @server.tool()
    def list_tileset_options() -> dict[str, Any]:
        """Describe supported local atlas layouts, distinct from private provider models."""
        return {
            "tile_sizes": [8, 16, 32, 64],
            "piece_sets": ["atlas", "topdown-15"],
            "max_canvas": 256,
            "ordering": "row-major; topdown-15 uses4x4 with15 populated cells",
            "semantic_masks": "provided by the authoring agent; not inferred from pixels",
        }

    @server.tool()
    async def generate_tileset(
        prompt: str,
        ctx: Context,
        tile_size: Annotated[int, Field(strict=True, ge=8, le=64)] = 16,
        columns: Count = 4,
        rows: Count = 4,
        piece_set: str = "atlas",
        tile_asset_ids: list[str] | None = None,
        drawing: dict[str, Any] | None = None,
        wait_seconds: Wait = 0,
    ) -> dict[str, Any]:
        """Assemble exact native tiles or request an agent-drawn atlas, preserving source IDs."""
        return await workflows.tileset(
            prompt,
            ctx,
            tile_size=tile_size,
            columns=columns,
            rows=rows,
            piece_set=piece_set,
            tile_asset_ids=tile_asset_ids,
            drawing=drawing,
            wait_seconds=wait_seconds,
        )

    @server.tool()
    def create_asset_upload(
        file_name: str,
        size_bytes: Annotated[int, Field(strict=True, ge=1, le=4194304)],
    ) -> dict[str, Any]:
        """Create an expiring local file:// slot for PNG bytes; no HTTP PUT endpoint."""
        return workflows.create_upload(file_name, size_bytes)

    @server.tool()
    def finalize_asset_upload(
        upload_id: str, display_name: str = "Uploaded sprite"
    ) -> dict[str, Any]:
        """Validate supplied local upload bytes and import once, with idempotent results."""
        return workflows.finalize_upload(upload_id, display_name)

    @server.tool()
    def report_integration_error(
        error_message: str,
        engine: str | None = None,
        asset_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a bounded local incident report; nothing is sent to an external service."""
        return workflows.report_integration_error(error_message, engine, asset_id, details)

    return workflows
