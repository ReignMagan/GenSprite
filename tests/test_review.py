import hashlib
import io

import pytest
from PIL import Image

from gensprite_mcp.assets import AssetStore
from gensprite_mcp.models import FrameAnimationRequest
from gensprite_mcp.review import review_asset


def sprite(store, points, size=(8, 8)):
    image = Image.new("RGBA", size)
    for point in points:
        image.putpixel(point, (255, 0, 0, 255))
    return store.save_image(image, "Review subject")


def test_review_reports_geometry_and_preserves_pixels(tmp_path):
    store = AssetStore(tmp_path)
    source = sprite(store, [(0, 0), (3, 3), (3, 4), (4, 3), (4, 4)])
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()
    }
    report, board = review_asset(store, source["asset_id"])
    assert report["kind"] == "sprite"
    assert report["metrics"]["visible_pixels"] == 5
    assert report["metrics"]["bounds"] == {"x": 0, "y": 0, "width": 5, "height": 5}
    assert report["metrics"]["edge_contact"] == ["top", "left"]
    assert report["metrics"]["component_count"] == 2
    assert report["metrics"]["isolated_pixel_count"] == 1
    assert report["metrics"]["palette_usage"] == {"#FF0000": 5}
    assert report["art_review_status"] == "agent_responsibility"
    assert any("intentional" in hint.lower() for hint in report["observations"])
    with Image.open(io.BytesIO(board)) as preview:
        assert preview.format == "PNG"
        assert max(preview.size) <= 1280
        assert (255, 0, 0) in preview.convert("RGB").get_flattened_data()
    assert before == {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()
    }


def test_diagonal_connections_are_not_stray_pixels(tmp_path):
    store = AssetStore(tmp_path)
    source = sprite(store, [(2, 2), (3, 3), (4, 4)])
    report, _ = review_asset(store, source["asset_id"])
    assert report["metrics"]["component_count"] == 1
    assert report["metrics"]["isolated_pixel_count"] == 0


def test_animation_review_keeps_order_timing_and_reports_placement(tmp_path):
    store = AssetStore(tmp_path)
    master = sprite(store, [(2, 3), (2, 4)])
    moved = sprite(store, [(4, 3), (4, 4)])
    animation = store.assemble_animation(
        FrameAnimationRequest(
            asset_id=master["asset_id"],
            frame_asset_ids=[master["asset_id"], moved["asset_id"]],
            durations_ms=[80, 240],
            name="walk",
            loop=True,
        )
    )
    report, board = review_asset(store, animation["animation_id"])
    assert report["kind"] == "animation"
    assert [frame["duration_ms"] for frame in report["frames"]] == [80, 240]
    assert report["frames"][1]["bounds_delta"] == {"x": 2, "y": 0, "width": 0, "height": 0}
    assert report["duration_ms"] == 320
    assert report["preview_path"] == str(animation["preview_path"])
    assert "playback" in report["limitations"].lower()
    with Image.open(io.BytesIO(board)) as preview:
        assert max(preview.size) <= 1280


@pytest.mark.parametrize("kind", ["sprite", "animation"])
def test_review_rejects_corrupted_sources(tmp_path, kind):
    store = AssetStore(tmp_path)
    master = sprite(store, [(2, 2)])
    identifier = master["asset_id"]
    path = master["png_path"]
    if kind == "animation":
        other = sprite(store, [(3, 2)])
        animation = store.assemble_animation(
            FrameAnimationRequest(
                asset_id=identifier,
                frame_asset_ids=[identifier, other["asset_id"]],
                durations_ms=[100, 100],
                name="idle",
                loop=True,
            )
        )
        identifier, path = animation["animation_id"], animation["frame_paths"][0]
    path.write_bytes(b"broken")
    with pytest.raises(ValueError, match="validation|integrity"):
        review_asset(store, identifier)


@pytest.mark.parametrize("identifier", ["../secret", "a_../secret", "n_000", "", None])
def test_review_rejects_invalid_identifiers(tmp_path, identifier):
    with pytest.raises(ValueError, match="ID"):
        review_asset(AssetStore(tmp_path), identifier)


def test_maximum_animation_review_is_bounded(tmp_path):
    store = AssetStore(tmp_path)
    poses = [
        sprite(store, [(100 + index, 100), (100 + index, 101)], (256, 256)) for index in range(16)
    ]
    animation = store.assemble_animation(
        FrameAnimationRequest(
            asset_id=poses[0]["asset_id"],
            frame_asset_ids=[pose["asset_id"] for pose in poses],
            durations_ms=[100] * 16,
            name="walk",
            loop=True,
        )
    )
    report, board = review_asset(store, animation["animation_id"])
    assert len(report["frames"]) == 16
    assert len(board) < 4 * 1024 * 1024
    with Image.open(io.BytesIO(board)) as preview:
        assert max(preview.size) <= 1280


def test_single_pose_review_keeps_heading_inside_board(tmp_path):
    store = AssetStore(tmp_path)
    master = sprite(store, [(2, 3), (2, 4)])
    animation = store.assemble_animation(
        FrameAnimationRequest(
            asset_id=master["asset_id"],
            frame_asset_ids=[master["asset_id"]],
            durations_ms=[120],
            name="pose",
            loop=False,
        )
    )
    _, board = review_asset(store, animation["animation_id"])
    with Image.open(io.BytesIO(board)) as preview:
        right_margin = preview.crop((preview.width - 8, 0, preview.width, 60)).convert("RGB")
        assert set(right_margin.get_flattened_data()) == {(16, 24, 32)}
