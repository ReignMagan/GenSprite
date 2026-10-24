import base64
import hashlib
import io
import struct
import zlib

import pytest
from PIL import Image

from gensprite_mcp.assets import AssetStore
from gensprite_mcp.image_ops import (
    auto_slice_asset,
    edit_sprite,
    get_asset_history,
    import_image,
    refine_sprite,
    register_image_tools,
    remove_background,
    rollback_asset,
    set_asset_alpha_cutoff,
)


def encoded_png(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def sample_image():
    image = Image.new("RGBA", (16, 16))
    image.putpixel((2, 3), (255, 0, 0, 255))
    image.putpixel((3, 3), (255, 0, 0, 255))
    return image


def read_image(result):
    with Image.open(result["png_path"]) as image:
        return image.copy()


def test_import_preserves_original_png_and_native_pixels(tmp_path):
    store = AssetStore(tmp_path)
    encoded = encoded_png(sample_image())
    result = import_image(store, "data:image/png;base64," + encoded, "Red mark")
    original = store._path("generated", result["asset_id"], "source.png")
    assert original.read_bytes() == base64.b64decode(encoded)
    assert read_image(result).getpixel((2, 3)) == (255, 0, 0, 255)
    manifest = store._manifest(result["asset_id"])
    assert manifest.description == "Red mark"
    assert manifest.template == "imported"
    assert manifest.metadata["original_sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert result["status"] == "ready_for_export"


@pytest.mark.parametrize("value", [
    "https://example.com/a.png", "AAAA!", "data:image/jpeg;base64,AA==",
])
def test_import_rejects_urls_and_malformed_base64_before_writes(tmp_path, value):
    with pytest.raises(ValueError):
        import_image(AssetStore(tmp_path), value)
    assert list(tmp_path.iterdir()) == []


def test_import_checks_decoded_canvas_before_loading_pixels(tmp_path):
    raw = bytearray(base64.b64decode(encoded_png(sample_image())))
    raw[16:24] = struct.pack(">II", 100000, 100000)
    raw[29:33] = struct.pack(">I", zlib.crc32(raw[12:29]))
    with pytest.raises(ValueError, match="dimension|canvas|256"):
        import_image(AssetStore(tmp_path), base64.b64encode(raw).decode())
    assert list(tmp_path.iterdir()) == []


def test_import_caps_encoded_and_decoded_input_size(tmp_path):
    with pytest.raises(ValueError, match="4 MiB"):
        import_image(AssetStore(tmp_path), "A" * (6 * 1024 * 1024))


def test_import_requires_explicit_alpha_refinement_and_keeps_original(tmp_path):
    store = AssetStore(tmp_path)
    image = sample_image()
    image.putpixel((4, 3), (255, 0, 0, 110))
    encoded = encoded_png(image)
    with pytest.raises(ValueError, match="alpha"):
        import_image(store, encoded)
    assert list(tmp_path.iterdir()) == []
    result = import_image(store, encoded, alpha_cutoff=100)
    assert read_image(result).getpixel((4, 3)) == (255, 0, 0, 255)
    lower = set_asset_alpha_cutoff(store, result["asset_id"], 200)
    assert read_image(lower).getpixel((4, 3))[3] == 0
    restored = set_asset_alpha_cutoff(store, lower["asset_id"], 100)
    assert read_image(restored).getpixel((4, 3))[3] == 255


def test_refine_alpha_cutoff_recovers_soft_pixels_from_preserved_original(tmp_path):
    store = AssetStore(tmp_path)
    image = sample_image()
    image.putpixel((4, 3), (255, 0, 0, 110))
    first = import_image(store, encoded_png(image), alpha_cutoff=200)
    result = refine_sprite(store, first["asset_id"], alpha_cutoff=100)
    assert read_image(result).getpixel((4, 3)) == (255, 0, 0, 255)


def test_import_supports_opaque_sources_for_explicit_matte_removal(tmp_path):
    store = AssetStore(tmp_path)
    image = Image.new("RGB", (8, 8), "white")
    image.putpixel((3, 3), (255, 0, 0))
    source = import_image(store, encoded_png(image))
    assert store._manifest(source["asset_id"]).transparent is False
    result = remove_background(store, source["asset_id"], "#FFFFFF")
    assert read_image(result).getpixel((0, 0))[3] == 0
    assert read_image(result).getpixel((3, 3)) == (255, 0, 0, 255)


@pytest.mark.parametrize("kwargs", [
    {"alpha_cutoff": 0}, {"alpha_cutoff": True}, {"alpha_cutoff": 256},
    {"palette": []}, {"palette": ["#FF0000", "#ff0000"]},
])
def test_import_rejects_invalid_refinement_inputs_before_writes(tmp_path, kwargs):
    with pytest.raises(ValueError):
        import_image(AssetStore(tmp_path), encoded_png(sample_image()), **kwargs)
    assert list(tmp_path.iterdir()) == []


def test_edit_pipeline_is_immutable_and_obeys_locked_palette(tmp_path):
    store = AssetStore(tmp_path)
    result = import_image(store, encoded_png(sample_image()), palette=["#FF0000", "#00FF00"])
    before = result["png_path"].read_bytes()
    revised = edit_sprite(store, result["asset_id"], [
        {"op": "crop", "x": 0, "y": 0, "width": 8, "height": 8},
        {"op": "recolor", "from": "#FF0000", "to": "#00FF00"},
        {"op": "flip", "axis": "horizontal"},
        {"op": "set_pixels", "pixels": [{"x": 0, "y": 0, "color": "#FF0000"}]},
    ])
    image = read_image(revised)
    assert image.size == (8, 8)
    assert image.getpixel((5, 3)) == (0, 255, 0, 255)
    assert image.getpixel((0, 0)) == (255, 0, 0, 255)
    assert result["png_path"].read_bytes() == before
    assert store._manifest(revised["asset_id"]).parent_asset_id == result["asset_id"]


@pytest.mark.parametrize("edit", [
    {"op": "crop", "x": 10, "y": 0, "width": 8, "height": 8},
    {"op": "crop", "x": 0, "y": 0, "width": 7, "height": 8},
    {"op": "set_pixels", "pixels": [{"x": 16, "y": 0, "color": "#FF0000"}]},
    {"op": "set_pixels", "pixels": [{"x": True, "y": 0, "color": "#FF0000"}]},
    {"op": "recolor", "from": "#FF0000", "to": "#00FF00"},
    {"op": "flip", "axis": "diagonal"},
    {"op": "unknown"},
])
def test_invalid_edits_never_write_a_revision(tmp_path, edit):
    store = AssetStore(tmp_path)
    result = import_image(store, encoded_png(sample_image()))
    with pytest.raises(ValueError):
        edit_sprite(store, result["asset_id"], [edit])
    assert len(list((tmp_path / "generated").iterdir())) == 1


def test_quantization_maps_to_explicit_palette_without_dithering(tmp_path):
    store = AssetStore(tmp_path)
    source = import_image(store, encoded_png(sample_image()))
    result = refine_sprite(store, source["asset_id"], palette=["#EE0000"])
    image = read_image(result)
    assert image.getpixel((2, 3)) == (238, 0, 0, 255)
    assert image.getpixel((0, 0))[3] == 0
    assert store._manifest(result["asset_id"]).palette == ["#EE0000"]


def test_max_colors_quantization_bounds_palette_and_preserves_alpha(tmp_path):
    store = AssetStore(tmp_path)
    image = sample_image()
    image.putpixel((4, 3), (0, 255, 0, 255))
    result = import_image(store, encoded_png(image))
    revised = refine_sprite(store, result["asset_id"], max_colors=1)
    assert len(store.inspect_sprite(revised["asset_id"])["colors"]) == 1
    assert read_image(revised).getchannel("A").tobytes() == image.getchannel("A").tobytes()


def test_background_removal_only_floods_matching_border_connected_pixels(tmp_path):
    store = AssetStore(tmp_path)
    image = Image.new("RGBA", (8, 8), "white")
    for x, y in [(2, 2), (3, 2), (4, 2), (2, 3), (4, 3), (2, 4), (3, 4), (4, 4)]:
        image.putpixel((x, y), (255, 0, 0, 255))
    image.putpixel((7, 7), (0, 0, 0, 0))
    result = import_image(store, encoded_png(image))
    cleaned = remove_background(store, result["asset_id"], color="#FFFFFF")
    output = read_image(cleaned)
    assert output.getpixel((0, 0))[3] == 0
    assert output.getpixel((3, 3)) == (255, 255, 255, 255)
    assert output.getpixel((2, 2)) == (255, 0, 0, 255)
    assert store._manifest(cleaned["asset_id"]).metadata["operation"] == "remove_background"


def test_history_and_rollback_create_new_version_without_rewriting(tmp_path):
    store = AssetStore(tmp_path)
    first = import_image(store, encoded_png(sample_image()))
    second = edit_sprite(store, first["asset_id"], [{"op": "flip", "axis": "vertical"}])
    restored = rollback_asset(store, second["asset_id"], first["asset_id"])
    assert restored["asset_id"] not in {first["asset_id"], second["asset_id"]}
    assert read_image(restored).tobytes() == read_image(first).tobytes()
    history = get_asset_history(AssetStore(tmp_path), restored["asset_id"])
    assert [entry["asset_id"] for entry in history["versions"]] == [
        restored["asset_id"], second["asset_id"], first["asset_id"],
    ]
    unrelated = import_image(store, encoded_png(sample_image()))
    with pytest.raises(ValueError, match="ancestor|history"):
        rollback_asset(store, second["asset_id"], unrelated["asset_id"])


def test_slicing_preserves_component_pixels_and_pads_small_components(tmp_path):
    store = AssetStore(tmp_path)
    image = sample_image()
    image.putpixel((12, 12), (255, 0, 0, 255))
    source = import_image(store, encoded_png(image))
    result = auto_slice_asset(store, source["asset_id"])
    assert [item["rect"] for item in result["slices"]] == [
        {"x": 2, "y": 3, "width": 2, "height": 1},
        {"x": 12, "y": 12, "width": 1, "height": 1},
    ]
    assert all(read_image(item).size == (8, 8) for item in result["slices"])
    assert sum(sum(a == 255 for a in read_image(item).getchannel("A").get_flattened_data())
               for item in result["slices"]) == 3
    assert all(store._manifest(item["asset_id"]).parent_asset_id == source["asset_id"]
               for item in result["slices"])


def test_slicing_never_discards_components_when_limit_is_exceeded(tmp_path):
    store = AssetStore(tmp_path)
    image = sample_image()
    image.putpixel((12, 12), (255, 0, 0, 255))
    source = import_image(store, encoded_png(image))
    with pytest.raises(ValueError, match="slice|component|limit"):
        auto_slice_asset(store, source["asset_id"], max_slices=1)
    assert len(list((tmp_path / "generated").iterdir())) == 1


def test_slicing_nested_component_does_not_duplicate_pixels(tmp_path):
    store = AssetStore(tmp_path)
    image = Image.new("RGBA", (16, 16))
    for coordinate in range(1, 15):
        for x, y in [(1, coordinate), (14, coordinate), (coordinate, 1), (coordinate, 14)]:
            image.putpixel((x, y), (255, 0, 0, 255))
    image.putpixel((7, 7), (255, 0, 0, 255))
    source = import_image(store, encoded_png(image))
    result = auto_slice_asset(store, source["asset_id"])
    assert result["slice_count"] == 2
    assert read_image(result["slices"][0]).getpixel((6, 6))[3] == 0
    assert sum(sum(a == 255 for a in read_image(item).getchannel("A").get_flattened_data())
               for item in result["slices"]) == 53


def test_alpha_reprocessing_rejects_tampered_original(tmp_path):
    store = AssetStore(tmp_path)
    result = import_image(store, encoded_png(sample_image()))
    store._path("generated", result["asset_id"], "source.png").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest"):
        set_asset_alpha_cutoff(store, result["asset_id"], 128)
    assert len(list((tmp_path / "generated").iterdir())) == 1


def test_history_rejects_parent_cycles(tmp_path):
    import json

    store = AssetStore(tmp_path)
    result = import_image(store, encoded_png(sample_image()))
    path = result["manifest_path"]
    manifest = json.loads(path.read_text())
    manifest["parent_asset_id"] = result["asset_id"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="cycle"):
        get_asset_history(store, result["asset_id"])


def test_registered_image_tools_return_real_pixel_results(tmp_path):
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("image tests")
    store = AssetStore(tmp_path)
    register_image_tools(server, store)
    function = server._tool_manager.get_tool("import_asset").fn
    result = function(encoded_png(sample_image()))
    assert read_image(result).getpixel((2, 3)) == (255, 0, 0, 255)
    function = server._tool_manager.get_tool("edit_sprite").fn
    edited = function(result["asset_id"], [{"op": "flip", "axis": "vertical"}])
    assert read_image(edited).getpixel((2, 12)) == (255, 0, 0, 255)
