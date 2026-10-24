import pytest
from PIL import Image

from gensprite_mcp.assets import AssetStore


def test_agent_artwork_and_revision_are_immutable_and_automatically_ready(tmp_path):
    store = AssetStore(tmp_path)
    image = Image.new("RGBA", (16, 16))
    image.putpixel((5, 5), (255, 0, 0, 255))
    original = store.save_image(image, "Agent-designed icon")
    assert original["status"] == "ready_for_export"
    image.putpixel((6, 5), (255, 0, 0, 255))
    edited = store.save_image(image, "Added a pixel", parent_asset_id=original["asset_id"])
    assert edited["asset_id"] != original["asset_id"]
    assert store._manifest(edited["asset_id"]).parent_asset_id == original["asset_id"]
    with Image.open(original["png_path"]) as first:
        assert first.getpixel((6, 5))[3] == 0
    with pytest.raises(ValueError, match="alpha"):
        image.putpixel((6, 5), (255, 0, 0, 128))
        store.save_image(image, "Invalid alpha")


def test_agent_animation_uses_supplied_frames_and_variable_timing(tmp_path):
    from gensprite_mcp.models import FrameAnimationRequest

    store = AssetStore(tmp_path)
    frames = []
    for x in (4, 5, 6):
        image = Image.new("RGBA", (16, 16))
        image.putpixel((x, 10), (0, 255, 0, 255))
        frames.append(store.save_image(image, "Agent motion pose")["asset_id"])
    result = store.assemble_animation(
        FrameAnimationRequest(
            asset_id=frames[0],
            frame_asset_ids=frames,
            durations_ms=[80, 120, 160],
            name="walk",
            loop=True,
        )
    )
    assert result["frame_count"] == 3
    assert store.validate_animation(result["animation_id"])["errors"] == []
    frames[1] = frames[0]
    with pytest.raises(ValueError, match="duplicate"):
        store.assemble_animation(
            FrameAnimationRequest(
                asset_id=frames[0],
                frame_asset_ids=frames,
                durations_ms=[80, 120, 160],
                name="walk",
                loop=True,
            )
        )


@pytest.mark.parametrize("positions,allow_duplicates", [([2, 3], False), ([2, 2], True)])
def test_imported_animation_preserves_pngs_with_hidden_rgb(tmp_path, positions, allow_duplicates):
    import base64
    import io

    from gensprite_mcp.image_ops import import_image
    from gensprite_mcp.models import FrameAnimationRequest

    store = AssetStore(tmp_path)
    ids, originals = [], []
    for index, x in enumerate(positions):
        image = Image.new("RGBA", (8, 8), (255, index * 100, 0, 0))
        image.putpixel((x, 2), (0, 255, 0, 255))
        originals.append(image.tobytes())
        raw = io.BytesIO()
        image.save(raw, format="PNG")
        asset = import_image(store, base64.b64encode(raw.getvalue()).decode(), "External pose")
        ids.append(asset["asset_id"])
    animation = store.assemble_animation(
        FrameAnimationRequest(
            asset_id=ids[0],
            frame_asset_ids=ids,
            durations_ms=[80, 120],
            name="walk",
            allow_duplicate_frames=allow_duplicates,
        )
    )
    assert animation["validation"]["errors"] == []
    for path, original in zip(animation["frame_paths"], originals, strict=True):
        with Image.open(path) as image:
            assert image.tobytes() == original


def test_hidden_rgb_changes_are_not_distinct_animation_poses(tmp_path):
    from gensprite_mcp.models import FrameAnimationRequest

    store = AssetStore(tmp_path)
    ids = []
    for color in ((255, 0, 0, 0), (0, 0, 255, 0)):
        image = Image.new("RGBA", (8, 8), color)
        image.putpixel((2, 2), (0, 255, 0, 255))
        ids.append(store.save_image(image, "Same visible pose")["asset_id"])
    with pytest.raises(ValueError, match="duplicate"):
        store.assemble_animation(
            FrameAnimationRequest(
                asset_id=ids[0],
                frame_asset_ids=ids,
                durations_ms=[80, 120],
                name="walk",
            )
        )
