from gensprite_mcp.assets import AssetStore
from gensprite_mcp.models import SpriteRequest


def test_projects_and_collections_persist_with_distinct_ids(tmp_path):
    from gensprite_mcp.catalog import Catalog

    catalog = Catalog(tmp_path)
    project = catalog.create_project("Icons", "Game icons")
    collection = catalog.create_collection("Inventory", project["project_id"])
    assert project["project_id"].startswith("q_")
    assert collection["collection_id"].startswith("c_")
    restarted = Catalog(tmp_path)
    assert restarted.list_projects()["projects"] == [project]
    assert restarted.list_collections(project["project_id"])["collections"] == [collection]
    assert restarted.list_projects()["total"] == 1
    assert restarted.list_projects()["truncated"] is False


def test_assignment_moves_projects_and_preserves_project_when_collection_removed(tmp_path):
    from gensprite_mcp.catalog import Catalog

    store = AssetStore(tmp_path)
    asset_id = store.create_sprite(SpriteRequest())["asset_id"]
    catalog = Catalog(tmp_path)
    first = catalog.create_project("First")["project_id"]
    second = catalog.create_project("Second")["project_id"]
    collection = catalog.create_collection("Inventory", second)["collection_id"]
    catalog.assign_assets_to_project([asset_id], first)
    catalog.assign_assets_to_collection([asset_id], collection)
    info = catalog.get_asset_metadata(asset_id)
    assert (info["project_id"], info["collection_id"]) == (second, collection)
    catalog.assign_assets_to_collection([asset_id])
    info = catalog.get_asset_metadata(asset_id)
    assert (info["project_id"], info["collection_id"]) == (second, None)
    catalog.assign_assets_to_collection([asset_id], collection)
    catalog.assign_assets_to_project([asset_id])
    info = catalog.get_asset_metadata(asset_id)
    assert (info["project_id"], info["collection_id"]) == (None, None)


def test_labels_metadata_and_recent_discovery_use_actual_files(tmp_path):
    from gensprite_mcp.catalog import Catalog

    store = AssetStore(tmp_path)
    first = store.create_sprite(SpriteRequest(description="First"))
    second = store.create_sprite(SpriteRequest(description="Second"))
    catalog = Catalog(tmp_path)
    catalog.update_asset_label(first["asset_id"], "Health")
    metadata = Catalog(tmp_path).get_asset_metadata(first["asset_id"])
    assert metadata["label"] == "Health"
    assert (metadata["width"], metadata["height"]) == (32, 32)
    assert metadata["palette"] == ["#7F1D1D", "#EF4444", "#FCA5A5"]
    assert metadata["sprite_url"] == first["png_path"].as_uri()
    assert metadata["version_id"] == first["asset_id"]
    assert metadata["parent_asset_id"] is None
    assert metadata["validation"]["technical_status"] == "passed"
    recent = catalog.list_recent_assets(limit=1)
    assert len(recent["assets"]) == 1
    assert recent["total"] == 2 and recent["truncated"]
    second["png_path"].write_bytes(b"broken PNG")
    recent = catalog.list_recent_assets()
    assert [item["asset_id"] for item in recent["assets"]] == [first["asset_id"]]
    assert recent["total"] == 1
    catalog.update_asset_label(first["asset_id"], None)
    assert catalog.get_asset_metadata(first["asset_id"])["label"] is None


def test_assignment_checks_every_asset_before_any_changes_and_filters_lists(tmp_path):
    import pytest

    from gensprite_mcp.catalog import Catalog

    store = AssetStore(tmp_path)
    asset_id = store.create_sprite(SpriteRequest())["asset_id"]
    catalog = Catalog(tmp_path)
    project = catalog.create_project("Icons")["project_id"]
    collection = catalog.create_collection("Inventory", project)["collection_id"]
    with pytest.raises(ValueError, match="not found"):
        catalog.assign_assets_to_collection([asset_id, "a_" + "0" * 32], collection)
    assert catalog.get_asset_metadata(asset_id)["project_id"] is None
    catalog.assign_assets_to_collection([asset_id], collection)
    catalog.assign_assets_to_project([asset_id], project)
    assert catalog.get_asset_metadata(asset_id)["collection_id"] == collection
    assert catalog.list_recent_assets(project_id=project)["total"] == 1
    assert catalog.list_recent_assets(collection_id=collection)["total"] == 1
    other = catalog.create_project("Other")["project_id"]
    catalog.assign_assets_to_project([asset_id], other)
    assert catalog.get_asset_metadata(asset_id)["collection_id"] is None
    assert catalog.list_recent_assets(project_id=project)["total"] == 0


def test_animation_outputs_report_actual_source_and_local_paths(tmp_path):
    from gensprite_mcp.catalog import Catalog
    from gensprite_mcp.models import AnimationRequest

    store = AssetStore(tmp_path)
    asset_id = store.create_sprite(SpriteRequest(template="knight"))["asset_id"]
    animation = store.generate_animation(AnimationRequest(asset_id=asset_id, motion="idle"))
    catalog = Catalog(tmp_path)
    outputs = catalog.list_animation_outputs(asset_id)
    assert outputs["total"] == 1
    output = outputs["animations"][0]
    assert output["animation_id"] == animation["animation_id"]
    assert output["source_asset_id"] == asset_id
    assert output["spritesheet_url"] == animation["spritesheet_path"].as_uri()
    assert len(output["frame_paths"]) == 4
    animation["spritesheet_path"].unlink()
    assert catalog.list_animation_outputs(asset_id)["total"] == 0


def test_private_preset_settings_and_references_survive_restart(tmp_path):
    from gensprite_mcp.catalog import Catalog

    store = AssetStore(tmp_path)
    asset_id = store.create_sprite(SpriteRequest())["asset_id"]
    catalog = Catalog(tmp_path)
    settings = {
        "width": 32,
        "height": 32,
        "palette": ["#00FF00"],
        "motion": {"duration_ms": 120},
        "transparent": True,
    }
    saved = catalog.save_private_preset("Green icons", settings, [asset_id])
    assert saved["preset_id"].startswith("s_")
    loaded = Catalog(tmp_path).get_preset_settings(saved["preset_id"])
    assert loaded["settings"] == settings
    assert loaded["reference_asset_ids"] == [asset_id]
    assert loaded["visibility"] == "private"
    assert catalog.list_presets()["presets"][0]["preset_id"] == saved["preset_id"]
    loaded["settings"]["width"] = 16
    assert catalog.get_preset_settings(saved["preset_id"])["settings"]["width"] == 32


def test_catalog_rejects_unbounded_or_invalid_inputs_before_mutations(tmp_path):
    import pytest

    from gensprite_mcp.catalog import Catalog

    catalog = Catalog(tmp_path)
    for name in ("", " ", "x" * 101, "Bad\x00name"):
        with pytest.raises(ValueError):
            catalog.create_project(name)
    for limit in (0, 201, True, "5"):
        with pytest.raises(ValueError, match="limit"):
            catalog.list_projects(limit)
        with pytest.raises(ValueError, match="limit"):
            catalog.list_recent_assets(limit=limit)
    for bad in ("../escape", "p_" + "0" * 32, "q_" + "0" * 32 + "' OR 1=1"):
        with pytest.raises(ValueError, match="ID"):
            catalog.create_collection("Bad", bad)
    for asset_ids in ([], ["a_" + "0" * 32] * 201, ["../secret"]):
        with pytest.raises(ValueError):
            catalog.assign_assets_to_project(asset_ids)
    for settings in ({"x": "x" * 65536}, {"x": float("nan")}, [1, 2], {"x": object()}):
        with pytest.raises(ValueError):
            catalog.save_private_preset("Bad", settings)
    with pytest.raises(ValueError, match="not found"):
        catalog.save_private_preset("Bad reference", {}, ["a_" + "0" * 32])
    assert catalog.list_projects()["total"] == 0
    assert catalog.list_presets()["total"] == 0


def test_catalog_rejects_database_and_asset_symlinks(tmp_path):
    import pytest

    from gensprite_mcp.catalog import Catalog

    outside = tmp_path / "outside.sqlite3"
    outside.write_bytes(b"outside must remain unchanged")
    root = tmp_path / "store"
    root.mkdir()
    try:
        (root / "catalog.sqlite3").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks requires Windows Developer Mode or privilege")
    with pytest.raises(ValueError, match="Catalog"):
        Catalog(root)
    assert outside.read_bytes() == b"outside must remain unchanged"


def test_catalog_registers_requested_tools_with_callable_asset_contract(tmp_path):
    import asyncio

    from mcp.server.fastmcp import FastMCP

    from gensprite_mcp.catalog import register_catalog_tools

    store = AssetStore(tmp_path)
    asset_id = store.create_sprite(SpriteRequest())["asset_id"]
    server = FastMCP("Catalog test")
    register_catalog_tools(server, store)

    async def exercise():
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == {
            "create_project",
            "list_projects",
            "create_collection",
            "list_collections",
            "assign_assets_to_project",
            "assign_assets_to_collection",
            "update_asset_label",
            "list_recent_assets",
            "get_asset_metadata",
            "list_animation_outputs",
            "list_presets",
            "get_preset_settings",
            "save_private_preset",
        }
        _, structured = await server.call_tool("get_asset_metadata", {"asset_id": asset_id})
        assert structured["asset_id"] == asset_id
        assert structured["validation"]["technical_status"] == "passed"

    asyncio.run(exercise())


def test_discovery_reports_lower_bound_when_scan_budget_is_exhausted(tmp_path, monkeypatch):
    import gensprite_mcp.catalog as module

    store = AssetStore(tmp_path)
    for _ in range(3):
        store.create_sprite(SpriteRequest())
    monkeypatch.setattr(module, "DISCOVERY_LIMIT", 2)
    result = module.Catalog(tmp_path).list_recent_assets()
    assert len(result["assets"]) == result["total"] == 2
    assert result["discovery_truncated"] is True
    assert result["total_is_exact"] is False
    assert result["truncated"] is True


def test_metadata_exposes_immutable_parent_version_and_current_validation(tmp_path):
    from PIL import Image

    from gensprite_mcp.catalog import Catalog

    store = AssetStore(tmp_path)
    first = store.create_sprite(SpriteRequest())
    with Image.open(first["png_path"]) as image:
        child = store.save_image(image.copy(), "Agent revision", parent_asset_id=first["asset_id"])
    metadata = Catalog(tmp_path).get_asset_metadata(child["asset_id"])
    assert metadata["version_id"] == child["asset_id"]
    assert metadata["parent_asset_id"] == first["asset_id"]
    assert metadata["schema_version"] == "1.0"
    assert metadata["source_sha256"] == metadata["manifest"]["source_sha256"]
    child["png_path"].write_bytes(b"corrupt")
    metadata = Catalog(tmp_path).get_asset_metadata(child["asset_id"])
    assert metadata["validation"]["technical_status"] == "failed"
    assert metadata["status"] == "failed"


def test_catalog_rechecks_sqlite_sidecar_paths_before_writing(tmp_path):
    import pytest

    from gensprite_mcp.catalog import Catalog

    catalog = Catalog(tmp_path / "store")
    outside = tmp_path / "outside"
    outside.write_bytes(b"preserve")
    try:
        (catalog.root / "catalog.sqlite3-journal").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks requires Windows Developer Mode or privilege")
    with pytest.raises(ValueError, match="Catalog"):
        catalog.create_project("Blocked")
    assert outside.read_bytes() == b"preserve"


def test_mcp_catalog_rejects_boolean_limit_instead_of_coercing_to_one(tmp_path):
    import asyncio

    import pytest
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError

    from gensprite_mcp.catalog import register_catalog_tools

    server = FastMCP("Catalog bounds")
    register_catalog_tools(server, AssetStore(tmp_path))
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("list_projects", {"limit": True}))
