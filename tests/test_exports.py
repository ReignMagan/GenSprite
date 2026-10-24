import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from gensprite_mcp.assets import AssetStore
from gensprite_mcp.models import AnimationRequest, SpriteRequest


def exporter(tmp_path):
    from gensprite_mcp.exports import ExportStore

    store = AssetStore(tmp_path / "store")
    return store, ExportStore(store)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_generic_still_exports_original_pixels_metadata_and_zip(tmp_path):
    store, exports = exporter(tmp_path)
    source = store.create_sprite(SpriteRequest())
    result = exports.export_asset(source["asset_id"])
    manifest = read_json(result["manifest_path"])
    package = Path(result["directory"])
    copied = package / "sources" / source["asset_id"] / "sprite.png"
    assert copied.read_bytes() == source["png_path"].read_bytes()
    assert manifest["primary_asset_id"] == source["asset_id"]
    assert manifest["assets"][0]["pivot"] == {"x": 16, "y": 31}
    assert manifest["assets"][0]["frames"][0]["duration_ms"] is None
    assert result["status"] == "ready_for_export"
    assert str(store.root) not in Path(result["manifest_path"]).read_text()
    with zipfile.ZipFile(result["zip_path"]) as archive:
        assert set(archive.namelist()) == {*manifest["files"], "export.json"}
        for name in archive.namelist():
            assert archive.read(name) == (package / name).read_bytes()
            assert ".." not in Path(name).parts
    for name, record in manifest["files"].items():
        assert hashlib.sha256((package / name).read_bytes()).hexdigest() == record["sha256"]


def test_animation_export_preserves_frames_rectangles_timing_and_master(tmp_path):
    store, exports = exporter(tmp_path)
    master = store.create_sprite(SpriteRequest(template="knight"))
    source = store.generate_animation(AnimationRequest(
        asset_id=master["asset_id"], motion="idle", duration_ms=80,
    ))
    result = exports.export_asset(source["animation_id"], "canvas")
    manifest = read_json(result["manifest_path"])
    animation = next(a for a in manifest["assets"] if a["asset_id"] == source["animation_id"])
    assert animation["source_asset_id"] == master["asset_id"]
    assert animation["loop"] is True
    assert animation["frames"][2]["rect"] == {"x": 64, "y": 0, "width": 32, "height": 32}
    assert [frame["duration_ms"] for frame in animation["frames"]] == [80] * 4
    assert len(manifest["assets"]) == 2
    root = Path(result["directory"])
    assert (root / animation["image"]).read_bytes() == source["spritesheet_path"].read_bytes()
    for frame, original in zip(animation["frames"], source["frame_paths"], strict=True):
        assert (root / frame["file"]).read_bytes() == original.read_bytes()


@pytest.mark.parametrize("target", ["phaser", "pixijs", "flame", "unity", "libgdx", "canvas"])
def test_engine_exports_have_honest_import_contract_and_loader_example(tmp_path, target):
    store, exports = exporter(tmp_path)
    source = store.create_sprite(SpriteRequest())
    result = exports.export_asset(source["asset_id"], target)
    manifest = read_json(result["manifest_path"])
    contract = read_json(Path(result["directory"]) / "import.json")
    assert contract["target"] == target
    assert contract["format"] == "gensprite-import-contract-v1"
    assert contract["assets"] == manifest["assets"]
    assert contract["engine_runtime_verified"] is False
    assert "loader" in " ".join(manifest["files"])
    assert "not executed" in (Path(result["directory"]) / "README.md").read_text()


def test_export_rejects_tampered_sources_and_bad_identifiers_without_outputs(tmp_path):
    store, exports = exporter(tmp_path)
    source = store.create_sprite(SpriteRequest())
    source["png_path"].write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="validation"):
        exports.export_asset(source["asset_id"])
    for bad in ["../secret", "a_" + "0" * 31, "n_" + "0" * 32 + "/file"]:
        with pytest.raises(ValueError, match="ID"):
            exports.export_asset(bad)
    with pytest.raises(ValueError, match="target"):
        exports.export_asset(source["asset_id"], "unreal-uasset")
    assert not (store.root / "exports").exists()


def test_godot_character_resource_has_atlas_regions_relative_durations_and_pivot(tmp_path):
    store, exports = exporter(tmp_path)
    master = store.create_sprite(SpriteRequest(template="knight"))
    animation = store.generate_animation(AnimationRequest(
        asset_id=master["asset_id"], motion="attack", duration_ms=90,
    ))
    result = exports.export_godot_character_package(master["asset_id"], [animation["animation_id"]])
    root = Path(result["directory"])
    resource = (root / "sprite_frames.tres").read_text()
    assert 'type="SpriteFrames"' in resource
    assert "region = Rect2(64, 0, 32, 32)" in resource
    assert '"duration": 0.09' in resource
    assert '"speed": 1.0' in resource
    assert '"loop": false' in resource
    assert '"name": &"attack"' in resource
    assert f'sources/{animation["animation_id"]}/spritesheet.png' in resource
    assert "offset = Vector2(-16, -31)" in (root / "loader.gd").read_text()
    other = store.create_sprite(SpriteRequest(template="knight"))
    with pytest.raises(ValueError, match="source"):
        exports.export_godot_character_package(other["asset_id"], [animation["animation_id"]])


def test_godot_tileset_rejects_unknown_atlas_layout(tmp_path):
    store, exports = exporter(tmp_path)
    source = store.create_sprite(SpriteRequest())
    with pytest.raises(ValueError, match="tileset"):
        exports.export_godot_tileset_package(source["asset_id"])


def test_godot_tileset_uses_recorded_geometry_and_tile_count(tmp_path):
    store, exports = exporter(tmp_path)
    image = Image.new("RGBA", (32, 16))
    image.putpixel((1, 1), (255, 0, 0, 255))
    source = store.save_image(image, "Tile atlas", asset_type="tileset", metadata={
        "tileset": {"tile_width": 8, "tile_height": 8, "columns": 4, "rows": 2,
                    "tile_count": 7},
    })
    result = exports.export_godot_tileset_package(source["asset_id"])
    resource = (Path(result["directory"]) / "tileset.tres").read_text()
    assert "texture_region_size = Vector2i(8, 8)" in resource
    assert "tile_size = Vector2i(8, 8)" in resource
    assert "2:1/0 = 0" in resource
    assert "3:1/0 = 0" not in resource
    png_path = Path(result["directory"]) / "sources" / source["asset_id"] / "sprite.png"
    with Image.open(png_path) as png:
        assert png.getpixel((1, 1)) == (255, 0, 0, 255)


def test_agent_animation_exports_variable_frame_timings_and_provenance(tmp_path):
    from gensprite_mcp.models import FrameAnimationRequest

    store, exports = exporter(tmp_path)
    images = []
    for x in [1, 2]:
        image = Image.new("RGBA", (8, 8))
        image.putpixel((x, 1), (255, 0, 0, 255))
        images.append(store.save_image(image, f"Frame {x}"))
    animation = store.assemble_animation(FrameAnimationRequest(
        asset_id=images[0]["asset_id"], frame_asset_ids=[item["asset_id"] for item in images],
        durations_ms=[40, 170], name="walk", loop=False,
    ))
    result = exports.export_asset(animation["animation_id"], "godot")
    contract = read_json(Path(result["directory"]) / "import.json")
    frames = contract["assets"][-1]["frames"]
    assert [frame["duration_ms"] for frame in frames] == [40, 170]
    assert [frame["source_asset_id"] for frame in frames] == [item["asset_id"] for item in images]
    resource = (Path(result["directory"]) / "sprite_frames.tres").read_text()
    assert '"duration": 0.04' in resource
    assert '"duration": 0.17' in resource
    phaser = exports.export_asset(animation["animation_id"], "phaser")
    loader = (Path(phaser["directory"]) / "loader.js").read_text()
    assert "duration: f.duration_ms}" in loader


def test_integration_dry_run_copy_verify_and_no_overwrite(tmp_path):
    store, exports = exporter(tmp_path)
    source = store.create_sprite(SpriteRequest())
    result = exports.export_asset(source["asset_id"], "godot")
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5")
    assert exports.detect_engine(str(project))["engine"] == "godot"
    before = sorted(project.rglob("*"))
    plan = exports.integrate_asset(result["export_id"], str(project))
    assert plan["executed"] is False
    assert sorted(project.rglob("*")) == before
    assert not exports.verify_integration(result["export_id"], str(project))["passed"]
    written = exports.integrate_asset(result["export_id"], str(project), execute=True)
    assert written["executed"] is True
    assert written["verification"]["passed"] is True
    assert written["verification"]["engine_runtime_verified"] is False
    with pytest.raises(ValueError, match="exists"):
        exports.integrate_asset(result["export_id"], str(project), execute=True)
    destination = Path(written["destination"])
    (destination / "import.json").write_text("changed")
    report = exports.verify_integration(result["export_id"], str(project))
    assert report["passed"] is False
    assert any("import.json" in error for error in report["errors"])


def test_integration_rejects_changed_export_and_manifest_traversal(tmp_path):
    store, exports = exporter(tmp_path)
    source = store.create_sprite(SpriteRequest())
    result = exports.export_asset(source["asset_id"])
    project = tmp_path / "project"
    project.mkdir()
    exported = Path(result["directory"]) / "import.json"
    exported.write_text("changed")
    with pytest.raises(ValueError, match="digest"):
        exports.integrate_asset(result["export_id"], str(project), execute=True)
    manifest = read_json(result["manifest_path"])
    manifest["files"] = {"../../outside.png": {"sha256": "0" * 64, "size": 1}}
    Path(result["manifest_path"]).write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="path"):
        exports.integrate_asset(result["export_id"], str(project), execute=True)
    assert list(project.iterdir()) == []


def test_integration_rolls_back_partial_files_on_write_failure(tmp_path, monkeypatch):
    store, exports = exporter(tmp_path)
    source = store.create_sprite(SpriteRequest())
    result = exports.export_asset(source["asset_id"])
    project = tmp_path / "project"
    project.mkdir()
    original = Path.open

    def fail_one_write(path, *args, **kwargs):
        if project in path.parents and path.name == "import.json" and args == ("xb",):
            raise OSError("simulated disk failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_one_write)
    with pytest.raises(OSError, match="disk failure"):
        exports.integrate_asset(result["export_id"], str(project), execute=True)
    assert not list(project.rglob("*.png"))
    assert not list(project.rglob("e_*"))


def test_integration_rolls_back_if_verification_raises(tmp_path, monkeypatch):
    store, exports = exporter(tmp_path)
    source = store.create_sprite(SpriteRequest())
    result = exports.export_asset(source["asset_id"])
    project = tmp_path / "project"
    project.mkdir()

    def failed_verification(*args):
        raise ValueError("Export changed during verification")

    monkeypatch.setattr(exports, "verify_integration", failed_verification)
    with pytest.raises(ValueError, match="changed"):
        exports.integrate_asset(result["export_id"], str(project), execute=True)
    assert not list(project.rglob("e_*"))


@pytest.mark.parametrize("name", ["../evil", "C:/evil", "a\\evil", "./evil", "a//evil"])
def test_integration_rejects_nonportable_inventory_paths(tmp_path, name):
    store, exports = exporter(tmp_path)
    source = store.create_sprite(SpriteRequest())
    result = exports.export_asset(source["asset_id"])
    manifest = read_json(result["manifest_path"])
    manifest["files"] = {name: {"sha256": "0" * 64, "size": 0}}
    Path(result["manifest_path"]).write_text(json.dumps(manifest))
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError, match="path"):
        exports.integrate_asset(result["export_id"], str(project), execute=True)
    assert list(project.iterdir()) == []


@pytest.mark.parametrize("name,content,engine", [
    ("package.json", '{"dependencies":{"pixi.js":"*"}}', "pixijs"),
    ("package.json", '{"devDependencies":{"phaser":"*"}}', "phaser"),
    ("pubspec.yaml", "dependencies:\n  flame: ^1.0.0\n", "flame"),
    ("build.gradle", "dependencies { api 'com.badlogicgames.gdx:gdx:1.0' }", "libgdx"),
    ("ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 6000", "unity"),
])
def test_engine_detection_reads_project_markers_only(tmp_path, name, content, engine):
    _, exports = exporter(tmp_path)
    project = tmp_path / "project"
    marker = project / name
    marker.parent.mkdir(parents=True)
    marker.write_text(content)
    before = marker.read_bytes()
    assert exports.detect_engine(str(project))["engine"] == engine
    assert marker.read_bytes() == before


def test_export_tools_register_actual_mcp_schemas(tmp_path):
    import asyncio

    from mcp.server.fastmcp import FastMCP

    from gensprite_mcp.exports import register_export_tools

    store, _ = exporter(tmp_path)
    server = FastMCP("export-tests")
    register_export_tools(server, store)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {
        "export_asset", "export_godot_character_package", "export_godot_tileset_package",
        "detect_engine", "integrate_asset", "verify_integration",
    }
    integrate = next(tool for tool in tools if tool.name == "integrate_asset")
    assert integrate.inputSchema["properties"]["execute"]["default"] is False


def make_directory_link(link, target):
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks unavailable: {exc}")


def test_integration_rejects_symlinked_destination_and_project(tmp_path):
    store, exports = exporter(tmp_path)
    source = store.create_sprite(SpriteRequest())
    result = exports.export_asset(source["asset_id"])
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    make_directory_link(project / "gensprite", outside)
    with pytest.raises(ValueError, match="[Ss]ymlink|[Rr]eparse"):
        exports.integrate_asset(result["export_id"], str(project), execute=True)
    make_directory_link(tmp_path / "linked_project", outside)
    with pytest.raises(ValueError, match="[Ss]ymlink|[Rr]eparse"):
        exports.detect_engine(str(tmp_path / "linked_project"))
    assert list(outside.iterdir()) == []
