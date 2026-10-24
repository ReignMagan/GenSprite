"""SpriteCook-style production flow powered by agent-authored pixels, not hosted models."""

import json
import re
from typing import Annotated, Any

from mcp import types
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from .assets import AssetStore
from .drawing import PixelDrawing
from .image_ops import _decode_input, import_image
from .jobs import JobManager
from .models import AnimationRequest, Canvas, FrameAnimationRequest, Size

Wait = Annotated[int, Field(strict=True, ge=0, le=30)]
Count = Annotated[int, Field(strict=True, ge=1, le=16)]


ART_DIRECTION = (
    "Act as a deliberate pixel artist. Establish subject, native size, perspective, light "
    "direction and a compact palette before drawing. Keep a readable silhouette at actual "
    "size, connected color clusters, purposeful outlines, and clear material contrast. "
    "Avoid stray pixels, muddy near-identical colors, and detail that obscures the pose. "
    "Preserve reference proportions, equipment, colors and facing across revisions. "
    "For motion, plan anticipation, action/contact and recovery as appropriate; show weight "
    "shifts and articulated limbs instead of merely translating the entire sprite. Keep "
    "ground contact and a stable pivot unless the action requires displacement. "
    "Choose frame durations for deliberate holds and fast actions. Review at native size "
    "and enlarged, using the actual pixels rather than assuming the prompt was fulfilled."
)


class Production:
    def __init__(self, store: AssetStore, jobs: JobManager):
        self.store, self.jobs = store, jobs

    async def _request(
        self, ctx: Context | None, prompt: str, reference: str | None = None
    ) -> dict:
        if ctx is None or not ctx.session.client_params.capabilities.sampling:
            raise ValueError(
                "Client sampling is unavailable. The authoring agent must supply drawing={rows,"
                "palette}, an image, or animation frame asset IDs. No image-provider key is needed."
            )
        messages = [
            types.SamplingMessage(
                role="user",
                content=types.TextContent(type="text", text=prompt),
            )
        ]
        if reference:
            import base64

            raw = self.store._path("generated", reference, "sprite.png").read_bytes()
            messages.append(
                types.SamplingMessage(
                    role="user",
                    content=types.ImageContent(
                        type="image",
                        data=base64.b64encode(raw).decode("ascii"),
                        mimeType="image/png",
                    ),
                )
            )
        response = await ctx.session.create_message(
            messages=messages,
            max_tokens=16000,
            include_context="none",
            related_request_id=ctx.request_id,
            system_prompt=(
                ART_DIRECTION + " Return only the requested JSON. "
                "Construct deliberate native-grid pixels. Use '.' for transparent pixels, "
                "one ASCII symbol per palette color, and #RRGGBB values. Never request "
                "credentials, files, shell commands or unrelated context."
            ),
        )
        content = response.content
        if not isinstance(content, types.TextContent) or len(content.text) > 262144:
            raise ValueError(
                "Agent sampling must return bounded JSON text containing pixel artwork"
            )
        text = content.text.strip()
        try:
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(text)
        except (ValueError, IndexError) as exc:
            raise ValueError(
                "Agent returned invalid artwork JSON; supply explicit pixel data"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError("Agent artwork must be a JSON object")
        return data

    async def generate(
        self,
        prompt: str,
        ctx: Context | None,
        *,
        width: int = 32,
        height: int = 32,
        drawing: dict | None = None,
        image: str | None = None,
        colors: list[str] | None = None,
        reference_asset_id: str | None = None,
        edit_asset_id: str | None = None,
        project_id: str | None = None,
        mode: str = "character",
        variations: int = 1,
        wait_seconds: int = 0,
        metadata: dict | None = None,
    ) -> dict:
        Canvas(width=width, height=height)
        if not isinstance(prompt, str) or not 1 <= len(prompt) <= 4000:
            raise ValueError("prompt must contain 1..4000 characters")
        if type(variations) is not int or not 1 <= variations <= 4:
            raise ValueError("variations must be 1..4")
        if image and drawing:
            raise ValueError("Supply image or drawing, not both")
        if type(wait_seconds) is not int or not 0 <= wait_seconds <= 30:
            raise ValueError("wait_seconds must be an integer from0 through30")
        if (image or drawing) and variations != 1:
            raise ValueError("Supplied artwork is one variation; submit distinct artwork per job")
        if image and _decode_input(image)[0].size != (width, height):
            raise ValueError("Imported image dimensions differ from the requested canvas")
        reference = edit_asset_id or reference_asset_id
        if reference and self.store.validate_sprite(reference)["errors"]:
            raise ValueError("Reference asset validation failed")
        if project_id:
            from .catalog import Catalog

            Catalog(self.store.root).list_collections(project_id=project_id, limit=1)
        prepared: list[PixelDrawing] = []
        for variant in range(variations):
            if image:
                break
            pixels = drawing
            if pixels is None:
                if width > 64 or height > 64:
                    raise ValueError("For canvases above 64x64, supply explicit agent pixel data")
                pixels = await self._request(
                    ctx,
                    (
                        f"Draw native {width}x{height} pixel art: {prompt}. "
                        f"Variation {variant + 1}. "
                        f"Perspective: {(metadata or {}).get('perspective', 'match the source')}. "
                        f"Approved colors: {colors or 'choose at most 32 coherent colors'}. "
                        "Preserve the supplied reference identity if present. Return "
                        '{"rows":["..."],"palette":{"X":"#RRGGBB"}} with every row exactly '
                        f"{width} symbols and exactly {height} rows. "
                        "No interpolation or antialiasing. Leave deliberate canvas margins and "
                        "make the silhouette readable before adding interior detail."
                    ),
                    reference,
                )
            parsed = PixelDrawing.model_validate(pixels)
            if parsed.image().size != (width, height):
                raise ValueError("Agent drawing dimensions differ from the requested canvas")
            prepared.append(parsed)

        def work() -> dict:
            assets = []
            for variant in range(variations):
                if image:
                    imported = import_image(self.store, image, prompt[:100], palette=colors)
                    origin = self.store._manifest(imported["asset_id"])
                    from PIL import Image

                    with Image.open(imported["png_path"]) as source_image:
                        saved = self.store.save_image(
                            source_image,
                            prompt,
                            palette=colors or origin.palette,
                            template="imported",
                            asset_type=mode,
                            parent_asset_id=edit_asset_id or origin.asset_id,
                            metadata={
                                **origin.metadata,
                                "original_asset_id": origin.asset_id,
                                "reference_asset_id": reference,
                                **(metadata or {}),
                            },
                        )
                else:
                    item = prepared[variant]
                    saved = self.store.save_image(
                        item.image(),
                        prompt,
                        palette=colors or list(item.palette.values()),
                        parent_asset_id=edit_asset_id,
                        asset_type=mode,
                        metadata={
                            "authoring": "connected_agent",
                            "reference_asset_id": reference,
                            **(metadata or {}),
                        },
                    )
                saved["sprite_url"] = saved["png_path"].as_uri()
                assets.append(saved)
            if project_id:
                from .catalog import Catalog

                Catalog(self.store.root).assign_assets_to_project(
                    [asset["asset_id"] for asset in assets],
                    project_id,
                )
            return {"assets": assets}

        submitted = self.jobs.submit("generate_game_art", work)
        return (
            await self.jobs.check(submitted["job_id"], wait_seconds) if wait_seconds else submitted
        )

    async def animate(
        self,
        asset_id: str,
        prompt: str,
        ctx: Context | None,
        *,
        frame_asset_ids: list[str] | None = None,
        frames: list[dict] | None = None,
        output_frames: int | None = None,
        duration_ms: int = 120,
        durations_ms: list[int] | None = None,
        loop: bool | None = None,
        output_format: str = "gif",
        wait_seconds: int = 0,
        perspective: str | None = None,
    ) -> dict:
        source = self.store._manifest(asset_id)
        if self.store.validate_sprite(asset_id)["errors"]:
            raise ValueError("Animation source validation failed")
        if output_format not in ("gif", "spritesheet"):
            raise ValueError("Local animation outputs are gif or spritesheet")
        if not isinstance(prompt, str) or not 1 <= len(prompt) <= 4000:
            raise ValueError("Motion prompt must contain 1..4000 characters")
        if frame_asset_ids and frames:
            raise ValueError("Supply frame asset IDs or pixel frames, not both")
        motion = re.sub(r"[^a-z0-9_]+", "_", prompt.lower()).strip("_")[:32] or "motion"
        if not motion[0].isalpha():
            motion = "motion_" + motion[:25]
        from .animation import is_native_knight

        native = (
            is_native_knight(self.store, source)
            and (perspective or source.metadata.get("perspective", "platformer")) == "platformer"
            and prompt.lower() in ("idle", "attack")
            and not frame_asset_ids
            and not frames
            and output_frames is None
        )
        count = len(frame_asset_ids or frames or []) or output_frames or 8
        if type(count) is not int or not 1 <= count <= 16:
            raise ValueError("Animation frame count must be 1..16")
        if not native and not frame_asset_ids and not frames:
            sampled = await self._request(
                ctx,
                (
                    f"Animate this exact {source.canvas.width}x{source.canvas.height} character. "
                    "Perspective: "
                    f"{perspective or source.metadata.get('perspective', 'match source')}. "
                    f"Motion: {prompt}. Return exactly {count} native-grid poses as "
                    '{"frames":[{"rows":["..."],"palette":{"X":"#RRGGBB"}}]}. '
                    f"Use ONLY colors {source.palette}. Preserve identity and pivot. "
                    "Keep feet planted unless motion requires lifting them. Plan distinct key "
                    "poses with anticipation, action and recovery where appropriate. Preserve "
                    "equipment size and anatomy; avoid whole-body sliding or random jitter. "
                    "No duplicate poses."
                ),
                asset_id,
            )
            frames = sampled.get("frames")
            if not isinstance(frames, list) or len(frames) != count:
                raise ValueError("Agent animation response has the wrong frame count")
        parsed = [PixelDrawing.model_validate(frame) for frame in (frames or [])]
        if output_frames is not None and count != output_frames:
            raise ValueError("Supplied poses differ from output_frames")

        def work() -> dict:
            if native:
                if durations_ms is not None or loop is not None:
                    from .animation import _write_animation
                    from .knight import draw_knight

                    count = 4 if prompt.lower() == "idle" else 6
                    images = [
                        draw_knight(
                            source.canvas.width,
                            source.canvas.height,
                            source.palette,
                            prompt.lower(),
                            i,
                        )
                        for i in range(count)
                    ]
                    if durations_ms is not None and len(durations_ms) != count:
                        raise ValueError("Every native pose must have one duration")
                    result = _write_animation(
                        self.store,
                        source,
                        images,
                        durations_ms or [duration_ms] * count,
                        prompt.lower(),
                        loop if loop is not None else prompt.lower() == "idle",
                        "agent_frames",
                    )
                else:
                    result = self.store.generate_animation(
                        AnimationRequest(
                            asset_id=asset_id, motion=prompt.lower(), duration_ms=duration_ms
                        )
                    )
            else:
                ids = list(frame_asset_ids or [])
                for frame in parsed:
                    saved = self.store.save_image(
                        frame.image(),
                        f"{motion} pose",
                        palette=source.palette,
                        parent_asset_id=asset_id,
                        asset_type=source.type,
                        metadata={"animation_source": asset_id},
                    )
                    ids.append(saved["asset_id"])
                result = self.store.assemble_animation(
                    FrameAnimationRequest(
                        asset_id=asset_id,
                        frame_asset_ids=ids,
                        name=motion,
                        durations_ms=durations_ms or [duration_ms] * len(ids),
                        loop=loop if loop is not None else motion in ("idle", "walk", "run"),
                    )
                )
            result["sprite_url"] = (
                result["spritesheet_path"]
                if output_format == "spritesheet"
                else result["preview_path"]
            ).as_uri()
            result["spritesheet_url"] = result["spritesheet_path"].as_uri()
            return result

        submitted = self.jobs.submit("animate_game_art", work)
        return (
            await self.jobs.check(submitted["job_id"], wait_seconds) if wait_seconds else submitted
        )


def register_production_tools(server: FastMCP, store: AssetStore, jobs: JobManager) -> Production:
    production = Production(store, jobs)

    @server.tool()
    def create_pixel_art(
        rows: list[str],
        palette: dict[str, str],
        description: str = "Agent-authored sprite",
        asset_type: str = "character",
        parent_asset_id: str | None = None,
    ) -> dict[str, Any]:
        """Render agent-designed symbol rows at native resolution. '.' means transparent.

        Palette maps single ASCII symbols to #RRGGBB. Exact width/height: 8..256; <=32 colors.
        Plan a readable silhouette and coherent shading clusters at actual size; avoid
        isolated placeholder pixels. Use a concise subject name in description. After creating
        the master, call review_asset and revise its actual pixels before animating. Publish
        finished assets with build_asset_library so the user receives named files and a gallery.
        Artwork quality belongs to the connected agent; no human approval gate is imposed.
        """
        drawing = PixelDrawing(rows=rows, palette=palette)
        return store.save_image(
            drawing.image(),
            description,
            list(drawing.palette.values()),
            asset_type=asset_type,
            parent_asset_id=parent_asset_id,
        )

    @server.tool()
    async def generate_game_art(
        prompt: str,
        ctx: Context,
        width: Size = 32,
        height: Size = 32,
        drawing: dict[str, Any] | None = None,
        image: str | None = None,
        colors: list[str] | None = None,
        reference_asset_id: str | None = None,
        edit_asset_id: str | None = None,
        project_id: str | None = None,
        mode: str = "character",
        variations: Count = 1,
        wait_seconds: Wait = 0,
    ) -> dict[str, Any]:
        """Generate agent-authored artwork then return a durable job/poll contract.

        Provide drawing={rows,palette} or base64 PNG image. If omitted, negotiated MCP sampling
        asks the connected agent for native-grid pixels. Unsupported clients get clear input
        instructions. No private provider model, credit balance, or image API is impersonated.
        """
        return await production.generate(
            prompt,
            ctx,
            width=width,
            height=height,
            drawing=drawing,
            image=image,
            colors=colors,
            reference_asset_id=reference_asset_id,
            edit_asset_id=edit_asset_id,
            project_id=project_id,
            mode=mode,
            variations=variations,
            wait_seconds=wait_seconds,
        )

    @server.tool()
    async def animate_game_art(
        asset_id: str,
        prompt: str,
        ctx: Context,
        frame_asset_ids: list[str] | None = None,
        frames: list[dict[str, Any]] | None = None,
        output_frames: Count | None = None,
        duration_ms: Annotated[int, Field(strict=True, ge=10, le=10000, multiple_of=10)] = 120,
        durations_ms: list[int] | None = None,
        loop: bool | None = None,
        output_format: str = "gif",
        wait_seconds: Wait = 0,
    ) -> dict[str, Any]:
        """Animate one immutable source using agent frame IDs/pixels or negotiated sampling.

        Every pose must use the source canvas and palette. Frame IDs preserve provenance.
        Built-in knight idle/attack plans work without sampling. Poll check_job_status.
        """
        return await production.animate(
            asset_id,
            prompt,
            ctx,
            frame_asset_ids=frame_asset_ids,
            frames=frames,
            output_frames=output_frames,
            duration_ms=duration_ms,
            durations_ms=durations_ms,
            loop=loop,
            output_format=output_format,
            wait_seconds=wait_seconds,
        )

    @server.tool()
    async def check_job_status(job_id: str, wait_seconds: Wait = 0) -> dict[str, Any]:
        """Poll a durable job; success only includes actual generated file outputs."""
        return await jobs.check(job_id, wait_seconds)

    @server.tool()
    def cancel_job(job_id: str) -> dict[str, Any]:
        """Cancel job reporting. Already-written immutable assets are preserved."""
        return jobs.cancel(job_id)

    @server.tool()
    def list_active_jobs() -> dict[str, Any]:
        """List queued/running work owned by this local server."""
        return jobs.active()

    @server.tool()
    def list_generation_models() -> dict[str, Any]:
        """Report the actual authoring mechanism; no hosted image models are bundled."""
        return {
            "models": [
                {
                    "id": "connected_agent",
                    "inputs": ["pixels", "PNG", "sampling"],
                    "sampling_optional": True,
                }
            ],
            "private_provider_models": [],
        }

    @server.tool()
    def get_credit_balance() -> dict[str, Any]:
        """Local operation is unmetered; this does not query or represent SpriteCook billing."""
        return {
            "mode": "local_unmetered",
            "credits": None,
            "subscription": None,
            "note": "Agent/model usage is controlled by your MCP client, not this server.",
        }

    return production
