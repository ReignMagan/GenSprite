import base64
import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from gensprite_mcp.assets import AssetStore
from gensprite_mcp.image_ops import import_image, set_asset_alpha_cutoff


def png(image):
    raw = io.BytesIO()
    image.save(raw, format="PNG")
    return raw.getvalue()


def prepare(store, **kwargs):
    from gensprite_mcp.preparation import prepare_sprite

    return prepare_sprite(store, **kwargs)


def test_preparation_preserves_large_source_and_pixel_grid(tmp_path):
    store = AssetStore(tmp_path / "store")
    native = Image.new("RGBA", (16, 8), "#123456")
    native.putpixel((4, 3), (255, 0, 0, 255))
    raw = png(native.resize((1024, 512), Image.Resampling.NEAREST))
    result = prepare(
        store, image=base64.b64encode(raw).decode(), width=16, height=16, padding=0,
        palette=["#123456", "#FF0000"],
    )
    with Image.open(result["png_path"]) as image:
        assert image.size == (16, 16)
        assert image.getpixel((4, 7)) == (255, 0, 0, 255)
        assert image.getpixel((4, 3))[3] == 0
        assert image.crop((0, 4, 16, 12)).tobytes() == native.tobytes()
    manifest = store._manifest(result["asset_id"])
    assert manifest.metadata["original_sha256"] == hashlib.sha256(raw).hexdigest()
    assert store._path("generated", result["asset_id"], "source.png").read_bytes() == raw
    with pytest.raises(ValueError, match="256"):
        import_image(store, base64.b64encode(raw).decode())


def test_preparation_accepts_local_png_and_recovers_soft_alpha_at_native_size(tmp_path):
    store = AssetStore(tmp_path / "store")
    native = Image.new("RGBA", (8, 8))
    native.putpixel((3, 3), (255, 0, 0, 255))
    native.putpixel((4, 3), (255, 0, 0, 110))
    path = tmp_path / "AI sprite.png"
    path.write_bytes(png(native.resize((512, 512), Image.Resampling.NEAREST)))
    result = prepare(store, image_path=str(path), width=8, height=8, padding=0)
    revised = set_asset_alpha_cutoff(store, result["asset_id"], 100)
    with Image.open(revised["png_path"]) as image:
        assert image.size == (8, 8)
        assert image.getpixel((4, 3)) == (255, 0, 0, 255)
    original = store._path("generated", result["asset_id"], "source.png")
    assert path.read_bytes() == original.read_bytes()


def test_preparation_removes_only_connected_matte_before_color_reduction(tmp_path):
    store = AssetStore(tmp_path)
    native = Image.new("RGBA", (8, 8), "white")
    for x, y in [(2, 2), (3, 2), (4, 2), (2, 3), (4, 3), (2, 4), (3, 4), (4, 4)]:
        native.putpixel((x, y), (255, 0, 0, 255))
    result = prepare(
        store, image=base64.b64encode(png(native)).decode(), width=8, height=8,
        padding=0, background_color="#FFFFFF", max_colors=2,
    )
    with Image.open(result["png_path"]) as image:
        assert image.getpixel((0, 0))[3] == 0
        assert image.getpixel((3, 3)) == (255, 255, 255, 255)
        assert image.getpixel((2, 2)) == (255, 0, 0, 255)


@pytest.mark.parametrize("kwargs", [
    {}, {"image_path": "relative.png"}, {"image": "https://example.com/sprite.png"},
    {"padding": 4}, {"alpha_cutoff": True}, {"max_colors": 0},
    {"palette": ["#FF0000"], "max_colors": 2},
    {"background_tolerance": 1},
])
def test_invalid_preparation_does_not_write_assets(tmp_path, kwargs):
    store = AssetStore(tmp_path / "store")
    if kwargs and "image_path" not in kwargs and "image" not in kwargs:
        kwargs["image"] = base64.b64encode(png(Image.new("RGBA", (8, 8), "red"))).decode()
    with pytest.raises(ValueError):
        prepare(store, width=8, height=8, **kwargs)
    assert not store.root.exists()


def test_preparation_rejects_oversized_source_before_decoding(tmp_path):
    path = tmp_path / "large.png"
    path.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="4 MiB"):
        prepare(AssetStore(tmp_path / "store"), image_path=str(path))
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize("operation", ["prepare", "import"])
def test_original_write_failure_never_commits_a_ready_asset(tmp_path, monkeypatch, operation):
    original_open = Path.open

    def fail_source(path, mode="r", *args, **kwargs):
        if path.name == "source.png" and mode == "xb":
            raise OSError("Source disk write failed")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_source)
    store = AssetStore(tmp_path)
    image = base64.b64encode(png(Image.new("RGBA", (8, 8), "red"))).decode()
    with pytest.raises(OSError, match="disk write"):
        if operation == "prepare":
            prepare(store, image=image)
        else:
            import_image(store, image)
    assert not list(tmp_path.rglob("manifest.json"))
