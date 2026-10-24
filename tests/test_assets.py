import json

import pytest
from PIL import Image
from pydantic import ValidationError

from gensprite_mcp.assets import AssetStore
from gensprite_mcp.models import ProjectProfile, SpriteRequest


def test_heart_acceptance_and_portable_manifest(tmp_path):
    store = AssetStore(tmp_path)
    result = store.create_sprite(SpriteRequest(description="A transparent heart icon"))
    with Image.open(result["png_path"]) as image:
        assert image.size == (32, 32)
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0)) == (0, 0, 0, 0)
        assert image.getpixel((16, 16))[3] == 255
        assert set(image.getchannel("A").get_flattened_data()) == {0, 255}
    manifest = json.loads(result["manifest_path"].read_text())
    assert manifest["frames"] == ["sprite.png"]
    assert manifest["canvas"] == {"width": 32, "height": 32}
    assert manifest["pivot"] == {"x": 16, "y": 31}
    assert manifest["technical_status"] == "passed"
    assert manifest["art_review_status"] == "agent_responsibility"
    assert manifest["approval_source"] == "automated_technical_checks"
    assert result["status"] == "ready_for_export"
    assert store.validate_sprite(result["asset_id"])["errors"] == []
    info = store.inspect_sprite(result["asset_id"])
    assert info["width"] == 32
    assert info["format"] == "PNG"
    assert set(info["colors"]) <= {"#7F1D1D", "#EF4444", "#FCA5A5"}


@pytest.mark.parametrize("width,height", [(8, 8), (16, 16), (23, 37), (256, 256)])
def test_custom_native_canvas_and_single_color_palette(tmp_path, width, height):
    store = AssetStore(tmp_path)
    result = store.create_sprite(SpriteRequest(width=width, height=height, palette=["#00ff00"]))
    info = store.inspect_sprite(result["asset_id"])
    assert (info["width"], info["height"]) == (width, height)
    assert info["colors"] == ["#00FF00"]
    assert store.validate_sprite(result["asset_id"])["technical_status"] == "passed"


@pytest.mark.parametrize("field,value", [
    ("width", 0), ("height", -1), ("width", 257), ("width", 32.5), ("width", True),
    ("palette", []), ("palette", ["red"]), ("palette", ["#12345G"]),
    ("palette", ["#aabbcc", "#AABBCC"]), ("palette", ["#000000"] * 33),
    ("template", "wizard"), ("description", "a" * 2001),
])
def test_invalid_requests_fail_before_writes(tmp_path, field, value):
    with pytest.raises(ValidationError):
        SpriteRequest(**{field: value})
    assert list(tmp_path.iterdir()) == []


def test_profile_survives_restart_and_locks_palette_and_canvas(tmp_path):
    store = AssetStore(tmp_path)
    saved = store.create_project_profile(ProjectProfile(name="Red icons", palette=["#FF0000"]))
    store = AssetStore(tmp_path)
    profile = store.get_project_profile(saved["profile_id"])
    assert profile.name == "Red icons"
    result = store.create_sprite(SpriteRequest(profile_id=saved["profile_id"]))
    assert store.inspect_sprite(result["asset_id"])["colors"] == ["#FF0000"]
    with pytest.raises(ValueError, match="palette"):
        store.create_sprite(SpriteRequest(profile_id=saved["profile_id"], palette=["#00FF00"]))
    with pytest.raises(ValueError, match="canvas"):
        store.create_sprite(SpriteRequest(profile_id=saved["profile_id"], width=17))


def test_creations_preserve_previous_asset_and_are_pixel_identical(tmp_path):
    store = AssetStore(tmp_path)
    first = store.create_sprite(SpriteRequest())
    original = first["png_path"].read_bytes()
    second = store.create_sprite(SpriteRequest())
    assert first["asset_id"] != second["asset_id"]
    assert first["png_path"].read_bytes() == original == second["png_path"].read_bytes()


@pytest.mark.parametrize("asset_id", [
    "../secret", "..\\secret", "C:\\secret", "/tmp/secret", "a_" + "0" * 32 + "/..",
])
def test_rejects_paths_instead_of_ids(tmp_path, asset_id):
    store = AssetStore(tmp_path)
    with pytest.raises(ValueError, match="ID"):
        store.inspect_sprite(asset_id)


@pytest.mark.parametrize("mutation,expected", [
    ("RGB", "RGBA"), ("size", "dimensions"), ("alpha", "alpha"),
    ("palette", "palette"), ("empty", "visible"), ("opaque", "transparent"),
])
def test_validation_reports_tampered_png(tmp_path, mutation, expected):
    store = AssetStore(tmp_path)
    result = store.create_sprite(SpriteRequest())
    with Image.open(result["png_path"]) as source:
        image = source.copy()
    if mutation == "RGB":
        image = image.convert("RGB")
    elif mutation == "size":
        image = Image.new("RGBA", (16, 16))
    elif mutation == "alpha":
        image.putpixel((16, 16), (239, 68, 68, 127))
    elif mutation == "palette":
        image.putpixel((16, 16), (0, 0, 255, 255))
    elif mutation == "empty":
        image = Image.new("RGBA", (32, 32))
    else:
        image = Image.new("RGBA", (32, 32), (239, 68, 68, 255))
    image.save(result["png_path"])
    report = store.validate_sprite(result["asset_id"])
    assert report["technical_status"] == "failed"
    assert report["status"] == "failed"
    assert any(expected in error for error in report["errors"])
    assert report["art_review_status"] == "agent_responsibility"


def test_corrupt_and_missing_assets_have_actionable_errors(tmp_path):
    store = AssetStore(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        store.inspect_sprite("a_" + "0" * 32)
    result = store.create_sprite(SpriteRequest())
    result["png_path"].write_bytes(b"not a PNG")
    report = store.validate_sprite(result["asset_id"])
    assert report["technical_status"] == "failed"
    assert any("PNG" in error for error in report["errors"])
    result["manifest_path"].write_text("{}")
    with pytest.raises(ValueError, match="manifest"):
        store.inspect_sprite(result["asset_id"])


def test_manifest_cannot_redirect_image_outside_store(tmp_path):
    store = AssetStore(tmp_path)
    result = store.create_sprite(SpriteRequest())
    manifest = json.loads(result["manifest_path"].read_text())
    manifest["frames"] = ["../../outside.png"]
    result["manifest_path"].write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest"):
        store.inspect_sprite(result["asset_id"])


def test_store_rejects_symlinked_asset_directory(tmp_path):
    root = tmp_path / "store"
    store = AssetStore(root)
    result = store.create_sprite(SpriteRequest())
    outside = tmp_path / "outside"
    result["png_path"].parent.rename(outside)
    try:
        result["png_path"].parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires Windows Developer Mode or privilege")
    with pytest.raises(ValueError, match="directory"):
        store.inspect_sprite(result["asset_id"])
