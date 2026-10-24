import asyncio
import io

import pytest
from PIL import Image

from gensprite_mcp.assets import AssetStore
from gensprite_mcp.jobs import JobManager
from gensprite_mcp.models import SpriteRequest
from gensprite_mcp.production import Production
from gensprite_mcp.workflows import Workflows


def test_real_character_run_tileset_and_expiring_local_upload(tmp_path):
    async def exercise():
        store = AssetStore(tmp_path)
        jobs = JobManager(tmp_path)
        workflow = Workflows(store, Production(store, jobs), jobs)
        knight = store.create_sprite(SpriteRequest(template="knight"))
        run = await workflow.character_run(knight["asset_id"], "platformer", None)
        for item in run["jobs"]:
            await jobs.check(item["job_id"], 2)
        status = workflow.check_character_run(run["run_id"])
        assert status["status"] == "completed"
        assert len(status["assets"]) == 2
        tiles = []
        for color in ((255, 0, 0, 255), (0, 255, 0, 255)):
            saved = store.save_image(Image.new("RGBA", (8, 8), color), "Solid tile")
            tiles.append(saved["asset_id"])
        atlas = await workflow.tileset(
            "Two tiles", None, tile_size=8, columns=2, rows=1, tile_asset_ids=tiles
        )
        result = await jobs.check(atlas["job_id"], 2)
        assert result["status"] == "completed"
        asset = result["output"]["assets"][0]
        assert store._manifest(asset["asset_id"]).metadata["tileset"]["tile_count"] == 2
        with Image.open(asset["png_path"]) as image:
            assert image.size == (16, 8)
            assert image.getpixel((0, 0)) == (255, 0, 0, 255)
            assert image.getpixel((8, 0)) == (0, 255, 0, 255)
        raw = io.BytesIO()
        Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(raw, format="PNG")
        upload = workflow.create_upload("tile.png", len(raw.getvalue()))
        store._path("uploads", upload["upload_id"], "payload.png").write_bytes(raw.getvalue())
        imported = workflow.finalize_upload(upload["upload_id"])
        assert workflow.finalize_upload(upload["upload_id"])["asset_id"] == imported["asset_id"]
        expired = workflow.create_upload("old.png", 1)
        record = workflow._read("uploads", expired["upload_id"])
        record["expires_at"] = 0
        workflow._write("uploads", expired["upload_id"], record)
        with pytest.raises(ValueError, match="expired"):
            workflow.finalize_upload(expired["upload_id"])

    asyncio.run(exercise())


def test_interrupted_partial_character_run_cannot_report_completed(tmp_path):
    async def exercise():
        store = AssetStore(tmp_path)
        jobs = JobManager(tmp_path)
        workflow = Workflows(store, Production(store, jobs), jobs)
        job = jobs.submit("motion", lambda: {"frame_count": 4})
        await jobs.check(job["job_id"], 2)
        run_id = "r_" + "a" * 32
        workflow._write(
            "runs",
            run_id,
            {
                "run_id": run_id,
                "character_id": "a_" + "0" * 32,
                "status": "running",
                "requested_motions": ["idle", "attack"],
                "submission_complete": False,
                "jobs": [{"job_id": job["job_id"]}],
            },
        )
        restarted = Workflows(store, Production(store, jobs), jobs)
        assert restarted.check_character_run(run_id)["status"] == "failed"

    asyncio.run(exercise())


def test_local_integration_reports_are_bounded_and_persisted(tmp_path):
    store = AssetStore(tmp_path)
    jobs = JobManager(tmp_path)
    workflow = Workflows(store, Production(store, jobs), jobs)
    asset = store.create_sprite(SpriteRequest(template="heart"))
    report = workflow.report_integration_error(
        "Loader rejected a path",
        "canvas",
        asset["asset_id"],
        {"path": "sprite.png"},
    )
    assert report["delivery"] == "local_only"
    assert workflow._read("reports", report["report_id"])["details"] == {"path": "sprite.png"}
    with pytest.raises(ValueError, match="8000"):
        workflow.report_integration_error("X" * 8001)
    with pytest.raises(ValueError, match="64 KiB"):
        workflow.report_integration_error("Too large", details={"data": "X" * 65536})
    with pytest.raises(ValueError):
        workflow.report_integration_error("Bad ID", asset_id="../private")


def test_tileset_rejects_ambiguous_artwork_inputs(tmp_path):
    store = AssetStore(tmp_path)
    jobs = JobManager(tmp_path)
    workflow = Workflows(store, Production(store, jobs), jobs)
    with pytest.raises(ValueError, match="not both"):
        asyncio.run(workflow.tileset("Ambiguous", None, drawing={}, tile_asset_ids=[]))
