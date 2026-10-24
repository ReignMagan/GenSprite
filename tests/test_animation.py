import json

import pytest
from PIL import Image
from pydantic import ValidationError

from gensprite_mcp.assets import AssetStore
from gensprite_mcp.models import AnimationRequest, SpriteRequest


def test_knight_master_is_native_rgba_and_automatically_ready(tmp_path):
    store = AssetStore(tmp_path)
    result = store.create_sprite(SpriteRequest(template="knight", description="Silver knight"))
    info = store.inspect_sprite(result["asset_id"])
    assert (info["width"], info["height"], info["mode"]) == (32, 32, "RGBA")
    assert info["manifest"]["type"] == "character"
    assert info["manifest"]["template"] == "knight"
    assert len(info["colors"]) >= 5
    assert result["validation"]["technical_status"] == "passed"
    assert result["status"] == "ready_for_export"


@pytest.mark.parametrize("motion,count,duration,loop", [
    ("idle", 4, 120, True), ("attack", 6, 80, False),
])
def test_animation_package_contract(tmp_path, motion, count, duration, loop):
    store = AssetStore(tmp_path)
    master = store.create_sprite(SpriteRequest(template="knight"))
    before = master["png_path"].read_bytes()
    result = store.generate_animation(AnimationRequest(
        asset_id=master["asset_id"], motion=motion, duration_ms=duration,
    ))
    manifest = json.loads(result["manifest_path"].read_text())
    assert manifest["source_asset_id"] == master["asset_id"]
    assert manifest["motion"] == motion
    assert manifest["loop"] is loop
    assert manifest["pivot"] == {"x": 16, "y": 31}
    assert len(manifest["frames"]) == count
    images = []
    for i, frame in enumerate(manifest["frames"]):
        assert frame["file"] == f"{i:03}.png"
        assert frame["duration_ms"] == duration
        assert frame["rect"] == {"x": 32 * i, "y": 0, "width": 32, "height": 32}
        with Image.open(result["manifest_path"].parent / frame["file"]) as image:
            assert image.size == (32, 32)
            assert image.mode == "RGBA"
            images.append(image.tobytes())
    assert len(set(images)) == count
    with Image.open(result["spritesheet_path"]) as strip:
        assert strip.size == (32 * count, 32)
        for i, pixels in enumerate(images):
            assert strip.crop((32 * i, 0, 32 * (i + 1), 32)).tobytes() == pixels
    with Image.open(result["preview_path"]) as preview:
        assert preview.n_frames == count
        for i in range(count):
            preview.seek(i)
            assert preview.info["duration"] == duration
    assert master["png_path"].read_bytes() == before
    if motion == "idle":
        with Image.open(master["png_path"]) as image:
            assert images[0] == image.tobytes()
    assert result["status"] == "ready_for_export"
    assert store.validate_animation(result["animation_id"])["technical_status"] == "passed"
    assert AssetStore(tmp_path).validate_animation(result["animation_id"])["errors"] == []


@pytest.mark.parametrize("data", [
    {"motion": "walk"}, {"duration_ms": 0}, {"duration_ms": 125},
    {"duration_ms": True}, {"asset_id": "../secret"},
])
def test_invalid_animation_requests(data):
    values = {"asset_id": "a_" + "0" * 32, "motion": "idle", **data}
    with pytest.raises(ValidationError):
        AnimationRequest(**values)


def test_knight_rejects_small_canvas():
    with pytest.raises(ValidationError, match="32"):
        SpriteRequest(template="knight", width=16, height=16)


def test_animation_rejects_unsupported_or_modified_master(tmp_path):
    store = AssetStore(tmp_path)
    heart = store.create_sprite(SpriteRequest())
    with pytest.raises(ValueError, match="knight"):
        store.generate_animation(AnimationRequest(asset_id=heart["asset_id"], motion="idle"))
    knight = store.create_sprite(SpriteRequest(template="knight"))
    knight["png_path"].write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="validation"):
        store.generate_animation(AnimationRequest(asset_id=knight["asset_id"], motion="idle"))


@pytest.mark.parametrize("filename", ["000.png", "spritesheet.png", "preview.gif"])
def test_animation_validation_detects_modified_outputs(tmp_path, filename):
    store = AssetStore(tmp_path)
    master = store.create_sprite(SpriteRequest(template="knight"))
    result = store.generate_animation(AnimationRequest(asset_id=master["asset_id"], motion="idle"))
    (result["manifest_path"].parent / filename).write_bytes(b"corrupt")
    report = store.validate_animation(result["animation_id"])
    assert report["technical_status"] == "failed"
    assert report["status"] == "failed"
    assert any(filename in error for error in report["errors"])


def test_animation_validation_checks_master_and_manifest_paths(tmp_path):
    store = AssetStore(tmp_path)
    master = store.create_sprite(SpriteRequest(template="knight"))
    result = store.generate_animation(AnimationRequest(asset_id=master["asset_id"], motion="idle"))
    master["png_path"].write_bytes(b"corrupt")
    assert store.validate_animation(result["animation_id"])["technical_status"] == "failed"
    manifest = json.loads(result["manifest_path"].read_text())
    manifest["frames"][0]["file"] = "../../outside.png"
    result["manifest_path"].write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest"):
        store.validate_animation(result["animation_id"])
