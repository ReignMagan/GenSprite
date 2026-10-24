import asyncio
import json

import pytest
from PIL import Image

from gensprite_mcp.assets import AssetStore
from gensprite_mcp.jobs import JobManager
from gensprite_mcp.production import Production
from gensprite_mcp.ui_kits import UIKits, register_ui_kit_tools


def drawing(color="#FF0000", width=16, height=16):
    rows = ["." * width for _ in range(height)]
    rows[3] = "." * 3 + "XX" + "." * (width - 5)
    return {"rows": rows, "palette": {"X": color}}


def service(tmp_path):
    store = AssetStore(tmp_path)
    jobs = JobManager(tmp_path)
    return UIKits(store, Production(store, jobs), jobs)


async def prepare_kit(kits):
    kit = kits.create_ui_kit("Red buttons", "Compact native-grid controls")
    kit = await kits.generate_ui_kit_concepts(
        kit["ui_kit_id"],
        None,
        drawings=[drawing()],
        width=16,
        height=16,
        wait_seconds=5,
    )
    kits.select_ui_kit_concept(kit["ui_kit_id"], kit["concepts"][0])
    return await kits.generate_ui_kit_component_sheets(
        kit["ui_kit_id"],
        None,
        drawings=[drawing()],
        width=16,
        height=16,
        wait_seconds=5,
    )


def test_create_and_restart_keep_real_initial_concept_and_instructions(tmp_path):
    kits = service(tmp_path)
    source = kits.store.save_image(Image.new("RGBA", (8, 8), "red"), "Agent concept")
    kit = kits.create_ui_kit("Red kit", "Sharp corners", source["asset_id"])
    assert kit["selected_concept_asset_id"] == source["asset_id"]
    restored = service(tmp_path).get_ui_kit(kit["ui_kit_id"])
    assert restored["instructions"] == "Sharp corners"
    assert restored["concepts"] == [source["asset_id"]]
    assert service(tmp_path).list_ui_kits()["ui_kits"][0]["ui_kit_id"] == kit["ui_kit_id"]


def test_concept_jobs_capture_actual_outputs_on_poll(tmp_path):
    async def run():
        kits = service(tmp_path)
        kit = kits.create_ui_kit("Two choices")
        pending = await kits.generate_ui_kit_concepts(
            kit["ui_kit_id"],
            None,
            drawings=[drawing(), drawing("#00FF00")],
            width=16,
            height=16,
        )
        assert len(pending["jobs"]) == 2
        for job in pending["jobs"]:
            await kits.jobs.check(job["job_id"], 5)
        result = kits.get_ui_kit(kit["ui_kit_id"])
        assert len(result["concepts"]) == 2
        assert all(job["status"] == "completed" for job in result["jobs"])
        path = kits.store._path("generated", result["concepts"][1], "sprite.png")
        with Image.open(path) as image:
            assert image.getpixel((3, 3)) == (0, 255, 0, 255)
        assert service(tmp_path).get_ui_kit(kit["ui_kit_id"])["concepts"] == result["concepts"]

    asyncio.run(run())


def test_selection_rejects_other_assets_and_sheet_generation_requires_selection(tmp_path):
    async def run():
        kits = service(tmp_path)
        kit = kits.create_ui_kit("Unselected")
        other = kits.store.save_image(Image.new("RGBA", (8, 8), "red"), "Unrelated")
        with pytest.raises(ValueError, match="concept|owned"):
            kits.select_ui_kit_concept(kit["ui_kit_id"], other["asset_id"])
        with pytest.raises(ValueError, match="select|concept"):
            await kits.generate_ui_kit_component_sheets(
                kit["ui_kit_id"],
                None,
                drawings=[drawing()],
                width=16,
                height=16,
            )

    asyncio.run(run())


def test_explicit_components_finalize_to_portable_crops_and_reuse_assets(tmp_path):
    async def run():
        kits = service(tmp_path)
        kit = await prepare_kit(kits)
        source = kit["component_sheets"][0]
        extracted = kits.extract_ui_kit_components(
            kit["ui_kit_id"],
            [
                {
                    "name": "button",
                    "source_asset_id": source,
                    "x": 0,
                    "y": 0,
                    "width": 8,
                    "height": 8,
                    "border": {"left": 1, "right": 1, "top": 1, "bottom": 1},
                }
            ],
        )
        assert extracted["quality_summary"]["technical_status"] == "passed"
        result = kits.finalize_ui_kit(kit["ui_kit_id"])
        assert result["status"] == "finalized"
        manifest = json.loads(result["manifest_path"].read_text())
        component = manifest["components"][0]
        assert component["name"] == "button"
        assert component["border"] == {"left": 1, "right": 1, "top": 1, "bottom": 1}
        assert component["file"] == "components/button.png"
        with Image.open(result["manifest_path"].parent / component["file"]) as image:
            assert image.size == (8, 8)
            assert image.getpixel((3, 3)) == (255, 0, 0, 255)
        assert kits.store._manifest(component["asset_id"]).parent_asset_id == source
        assert kits.finalize_ui_kit(kit["ui_kit_id"])["components"] == result["components"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"name": "../outside"},
        {"x": 12},
        {"width": 257},
        {"x": True},
        {"border": {"left": 4, "right": 4, "top": 1, "bottom": 1}},
    ],
)
def test_component_rects_and_nine_patch_borders_are_strict(tmp_path, change):
    async def run():
        kits = service(tmp_path)
        kit = await prepare_kit(kits)
        component = {
            "name": "button",
            "source_asset_id": kit["component_sheets"][0],
            "x": 0,
            "y": 0,
            "width": 8,
            "height": 8,
            **change,
        }
        with pytest.raises(ValueError):
            kits.extract_ui_kit_components(kit["ui_kit_id"], [component])
        assert kits.get_ui_kit(kit["ui_kit_id"])["components"] == []

    asyncio.run(run())


def test_auto_extraction_honestly_labels_components_and_reuses_real_slices(tmp_path):
    async def run():
        kits = service(tmp_path)
        kit = await prepare_kit(kits)
        extracted = kits.extract_ui_kit_components(kit["ui_kit_id"])
        assert extracted["components"][0]["name"] == "component_01"
        assert extracted["quality_summary"]["labels"] == "placeholder"
        before = set((tmp_path / "generated").iterdir())
        result = kits.finalize_ui_kit(kit["ui_kit_id"])
        assert set((tmp_path / "generated").iterdir()) == before
        component = result["components"][0]
        with Image.open(result["manifest_path"].parent / component["file"]) as image:
            assert image.size == (8, 8)
            assert sum(a == 255 for a in image.getchannel("A").get_flattened_data()) == 2

    asyncio.run(run())


def test_quality_summary_flags_overlapping_and_empty_geometry(tmp_path):
    async def run():
        kits = service(tmp_path)
        kit = await prepare_kit(kits)
        source = kit["component_sheets"][0]
        extracted = kits.extract_ui_kit_components(
            kit["ui_kit_id"],
            [
                {"name": "button", "source_asset_id": source, "x": 0, "y": 0, "w": 8, "h": 8},
                {"name": "overlap", "source_asset_id": source, "x": 1, "y": 0, "w": 8, "h": 8},
                {"name": "empty", "source_asset_id": source, "x": 8, "y": 8, "w": 8, "h": 8},
            ],
        )
        assert {issue["code"] for issue in extracted["quality_summary"]["issues"]} >= {
            "overlapping_components",
            "empty_component",
        }
        with pytest.raises(ValueError, match="empty|geometry"):
            kits.finalize_ui_kit(kit["ui_kit_id"])

    asyncio.run(run())


def test_quality_summary_stays_bounded_for_64_overlapping_components(tmp_path):
    async def run():
        kits = service(tmp_path)
        kit = await prepare_kit(kits)
        components = [
            {
                "name": f"button_{index}",
                "source_asset_id": kit["component_sheets"][0],
                "x": 0,
                "y": 0,
                "width": 8,
                "height": 8,
            }
            for index in range(64)
        ]
        result = kits.extract_ui_kit_components(kit["ui_kit_id"], components)
        assert result["quality_summary"]["technical_status"] == "passed"
        assert len(result["quality_summary"]["issues"]) <= 64
        assert result["quality_summary"]["omitted_issue_count"] > 0
        assert kits._path(kit["ui_kit_id"], "kit.json").stat().st_size <= 65536

    asyncio.run(run())


def test_finalization_detects_changed_portable_manifest(tmp_path):
    async def run():
        kits = service(tmp_path)
        kit = await prepare_kit(kits)
        kits.extract_ui_kit_components(kit["ui_kit_id"])
        finalized = kits.finalize_ui_kit(kit["ui_kit_id"])
        path = finalized["manifest_path"]
        manifest = json.loads(path.read_text())
        manifest["name"] = "Changed contract"
        path.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="integrity|digest"):
            kits.finalize_ui_kit(kit["ui_kit_id"])

    asyncio.run(run())


def test_finalization_detects_changed_component_png(tmp_path):
    async def run():
        kits = service(tmp_path)
        kit = await prepare_kit(kits)
        kits.extract_ui_kit_components(kit["ui_kit_id"])
        finalized = kits.finalize_ui_kit(kit["ui_kit_id"])
        component = finalized["manifest_path"].parent / finalized["components"][0]["file"]
        component.write_bytes(b"tampered")
        with pytest.raises(ValueError, match="integrity"):
            kits.finalize_ui_kit(kit["ui_kit_id"])

    asyncio.run(run())


def test_missing_sampling_never_fabricates_concept_assets(tmp_path):
    async def run():
        kits = service(tmp_path)
        kit = kits.create_ui_kit("Needs agent pixels")
        with pytest.raises(ValueError, match="sampling|drawing"):
            await kits.generate_ui_kit_concepts(kit["ui_kit_id"], None)
        assert kits.get_ui_kit(kit["ui_kit_id"])["concepts"] == []
        assert not (tmp_path / "generated").exists()

    asyncio.run(run())


def test_cancellation_preserves_assets_and_blocks_followup_work(tmp_path):
    async def run():
        kits = service(tmp_path)
        kit = kits.create_ui_kit("Cancel")
        pending = await kits.generate_ui_kit_concepts(
            kit["ui_kit_id"],
            None,
            drawings=[drawing()],
            width=16,
            height=16,
        )
        cancelled = kits.cancel_ui_kit(kit["ui_kit_id"])
        assert cancelled["status"] == "cancelled"
        await kits.jobs.check(pending["jobs"][0]["job_id"], 1)
        with pytest.raises(ValueError, match="cancelled"):
            await kits.generate_ui_kit_concepts(
                kit["ui_kit_id"],
                None,
                drawings=[drawing()],
                width=16,
                height=16,
            )

    asyncio.run(run())


@pytest.mark.parametrize("identifier", ["../outside", "u_" + "0" * 32 + "/..", "a_" + "0" * 32])
def test_kit_paths_reject_external_identifiers(tmp_path, identifier):
    with pytest.raises(ValueError, match="ID"):
        service(tmp_path).get_ui_kit(identifier)


def test_kit_json_reads_are_bounded(tmp_path):
    kits = service(tmp_path)
    kit = kits.create_ui_kit("Bounded record")
    kits._path(kit["ui_kit_id"], "kit.json").write_bytes(b" " * 65537)
    with pytest.raises(ValueError, match="64 KiB"):
        kits.get_ui_kit(kit["ui_kit_id"])


def test_kit_paths_reject_symlinked_directories(tmp_path):
    kits = service(tmp_path / "store")
    kit = kits.create_ui_kit("Safe paths")
    directory = kits._path(kit["ui_kit_id"])
    outside = tmp_path / "outside"
    directory.rename(outside)
    try:
        directory.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires Windows Developer Mode or privilege")
    with pytest.raises(ValueError, match="path|Symlink"):
        kits.get_ui_kit(kit["ui_kit_id"])


def test_ui_tools_keep_context_out_of_agent_input_schema(tmp_path):
    from mcp.server.fastmcp import FastMCP

    kits = service(tmp_path)
    server = FastMCP("ui-kit tests")
    registered = register_ui_kit_tools(server, kits.store, kits.production, kits.jobs)
    assert isinstance(registered, UIKits)
    tool = server._tool_manager.get_tool("generate_ui_kit_concepts")
    assert "ctx" not in tool.parameters["properties"]
    created = server._tool_manager.get_tool("create_ui_kit").fn("Controls")
    fetched = server._tool_manager.get_tool("get_ui_kit").fn(created["ui_kit_id"])
    assert fetched["name"] == "Controls"


def test_full_length_ui_instructions_reach_generated_assets(tmp_path):
    async def run():
        kits = service(tmp_path)
        instructions = "X" * 3000
        kit = kits.create_ui_kit("Detailed interface", instructions)
        kit = await kits.generate_ui_kit_concepts(
            kit["ui_kit_id"],
            None,
            drawings=[drawing()],
            width=16,
            height=16,
            wait_seconds=5,
        )
        assert kit["concepts"], kit
        assert kit["jobs"][0]["status"] == "completed"
        assert instructions in kits.store._manifest(kit["concepts"][0]).description

    asyncio.run(run())
