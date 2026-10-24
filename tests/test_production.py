import asyncio
import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from gensprite_mcp.assets import AssetStore
from gensprite_mcp.jobs import JobManager
from gensprite_mcp.production import Production


def drawing(x=3):
    rows = ["........"] * 8
    rows[5] = "." * x + "X" + "." * (7 - x)
    return {"rows": rows, "palette": {"X": "#00FF00"}}


def test_agent_generation_animation_and_actionable_sampling_fallback(tmp_path):
    async def exercise():
        jobs = JobManager(tmp_path)
        service = Production(AssetStore(tmp_path), jobs)
        submitted = await service.generate(
            "Agent-made icon", None, width=8, height=8, drawing=drawing()
        )
        result = await jobs.check(submitted["job_id"], 2)
        assert result["status"] == "completed"
        asset = result["output"]["assets"][0]
        assert asset["status"] == "ready_for_export"
        animation = await service.animate(
            asset["asset_id"],
            "walk",
            None,
            frames=[drawing(2), drawing(3), drawing(4)],
            output_frames=3,
            duration_ms=80,
        )
        output = await jobs.check(animation["job_id"], 2)
        assert output["status"] == "completed"
        assert output["output"]["frame_count"] == 3
        assert service.store.validate_animation(output["output"]["animation_id"])["errors"] == []
        with pytest.raises(ValueError, match="sampling|drawing"):
            await service.generate("Needs authoring", None)
        with pytest.raises(ValueError, match="dimensions"):
            await service.generate("Wrong size", None, drawing=drawing())

    asyncio.run(exercise())


def test_image_generation_preserves_workflow_metadata_and_edit_parent(tmp_path):
    async def exercise():
        store = AssetStore(tmp_path)
        jobs = JobManager(tmp_path)
        service = Production(store, jobs)
        parent = store.save_image(Image.new("RGBA", (8, 8), (0, 255, 0, 255)), "Master")
        raw = io.BytesIO()
        Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(raw, format="PNG")
        result = await service.generate(
            "Image-authored variant",
            None,
            width=8,
            height=8,
            image=base64.b64encode(raw.getvalue()).decode(),
            edit_asset_id=parent["asset_id"],
            metadata={"perspective": "isometric", "ui_kit_stage": "concept"},
            mode="ui",
        )
        output = await jobs.check(result["job_id"], 2)
        manifest = store._manifest(output["output"]["assets"][0]["asset_id"])
        assert manifest.parent_asset_id == parent["asset_id"]
        assert manifest.type == "ui"
        assert manifest.metadata["perspective"] == "isometric"
        assert manifest.metadata["original_asset_id"]

    asyncio.run(exercise())


def test_edited_native_knight_never_silently_redraws_original(tmp_path):
    from gensprite_mcp.image_ops import edit_sprite
    from gensprite_mcp.models import AnimationRequest, SpriteRequest

    store = AssetStore(tmp_path)
    original = store.create_sprite(SpriteRequest(template="knight"))
    flipped = edit_sprite(store, original["asset_id"], [{"op": "flip", "axis": "horizontal"}])
    with pytest.raises(ValueError, match="agent|source"):
        store.generate_animation(AnimationRequest(asset_id=flipped["asset_id"], motion="idle"))


def test_native_animation_respects_requested_timing_loop_and_output(tmp_path):
    from gensprite_mcp.models import SpriteRequest

    async def exercise():
        store = AssetStore(tmp_path)
        jobs = JobManager(tmp_path)
        service = Production(store, jobs)
        knight = store.create_sprite(SpriteRequest(template="knight"))
        job = await service.animate(
            knight["asset_id"],
            "idle",
            None,
            durations_ms=[40, 80, 120, 160],
            loop=False,
            output_format="spritesheet",
        )
        result = await jobs.check(job["job_id"], 2)
        assert result["status"] == "completed", result
        animation = result["output"]
        import json

        manifest = json.loads(Path(animation["manifest_path"]).read_text())
        assert [frame["duration_ms"] for frame in manifest["frames"]] == [40, 80, 120, 160]
        assert manifest["loop"] is False
        assert animation["sprite_url"].endswith("spritesheet.png")

    asyncio.run(exercise())


@pytest.mark.parametrize("length", [2001, 4000])
def test_generation_persists_the_full_accepted_prompt(tmp_path, length):
    async def exercise():
        store = AssetStore(tmp_path)
        jobs = JobManager(tmp_path)
        service = Production(store, jobs)
        prompt = "X" * length
        submitted = await service.generate(prompt, None, width=8, height=8, drawing=drawing())
        result = await jobs.check(submitted["job_id"], 2)
        assert result["status"] == "completed", result
        asset = result["output"]["assets"][0]
        assert store._manifest(asset["asset_id"]).description == prompt

    asyncio.run(exercise())
