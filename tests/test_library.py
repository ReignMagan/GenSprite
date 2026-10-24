import json
from pathlib import Path

import pytest

from gensprite_mcp.assets import AssetStore
from gensprite_mcp.catalog import Catalog
from gensprite_mcp.models import AnimationRequest, SpriteRequest


def publish(store, ids):
    from gensprite_mcp.library import build_asset_library

    return build_asset_library(store, ids)


def test_named_library_preserves_pixels_animation_and_repeated_entries(tmp_path):
    store = AssetStore(tmp_path)
    first = store.create_sprite(SpriteRequest(template="knight", description="Silver knight"))
    second = store.create_sprite(SpriteRequest(description="Health heart"))
    animation = store.generate_animation(
        AnimationRequest(asset_id=first["asset_id"], motion="attack")
    )
    Catalog(tmp_path).update_asset_label(first["asset_id"], "Hero knight")
    output = publish(store, [first["asset_id"]])
    entry = output["assets"][0]
    folder = tmp_path / "library" / entry["folder"]
    assert folder.name.startswith("hero-knight--")
    assert (folder / "sprite.png").read_bytes() == first["png_path"].read_bytes()
    motion = entry["animations"][0]
    motion_dir = folder / motion["folder"]
    assert (motion_dir / "preview.gif").read_bytes() == animation["preview_path"].read_bytes()
    assert (motion_dir / "manifest.json").read_bytes() == animation["manifest_path"].read_bytes()
    for frame in animation["frame_paths"]:
        assert (motion_dir / frame.name).read_bytes() == frame.read_bytes()
    before = Path(output["index_path"]).read_bytes()
    publish(store, [first["asset_id"]])
    assert Path(output["index_path"]).read_bytes() == before
    more = publish(store, [second["asset_id"]])
    assert more["asset_count"] == 2
    Catalog(tmp_path).update_asset_label(first["asset_id"], "Captain")
    renamed = publish(store, [first["asset_id"]])["assets"][0]
    assert renamed["folder"] == entry["folder"]
    assert renamed["name"] == "Captain"
    assert first["png_path"].read_bytes() == (folder / "sprite.png").read_bytes()


def test_names_and_gallery_text_are_safe(tmp_path):
    store = AssetStore(tmp_path)
    asset = store.create_sprite(SpriteRequest())
    Catalog(tmp_path).update_asset_label(asset["asset_id"], "../CON:<script>alert(1)</script>")
    output = publish(store, [asset["asset_id"]])
    html = Path(output["gallery_path"]).read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "prefers-reduced-motion" in html
    assert 'aria-pressed="false"' not in html  # no animation, no play control
    assert "fetch(" not in html
    folder = output["assets"][0]["folder"]
    assert "/" not in folder and "\\" not in folder and ":" not in folder
    assert (tmp_path / "library" / folder).is_dir()


@pytest.mark.parametrize("target", ["sprite.png", "asset.json", "index.html"])
def test_modified_managed_files_are_not_overwritten(tmp_path, target):
    store = AssetStore(tmp_path)
    asset = store.create_sprite(SpriteRequest())
    output = publish(store, [asset["asset_id"]])
    root = tmp_path / "library"
    path = (
        root / target if target == "index.html" else root / output["assets"][0]["folder"] / target
    )
    path.write_bytes(b"user changes")
    with pytest.raises(ValueError, match="modified|conflict"):
        publish(store, [asset["asset_id"]])
    assert path.read_bytes() == b"user changes"


def test_unknown_destination_and_invalid_index_are_preserved(tmp_path):
    store = AssetStore(tmp_path)
    asset = store.create_sprite(SpriteRequest())
    library = tmp_path / "library"
    library.mkdir()
    (library / "index.html").write_text("personal gallery")
    with pytest.raises(ValueError, match="unmanaged|conflict"):
        publish(store, [asset["asset_id"]])
    assert (library / "index.html").read_text() == "personal gallery"
    (library / "index.html").unlink()
    output = publish(store, [asset["asset_id"]])
    index_path = Path(output["index_path"])
    index = json.loads(index_path.read_text())
    index["files"]["../outside.txt"] = "a" * 64
    index_path.write_text(json.dumps(index))
    with pytest.raises(ValueError, match="Invalid|Unsafe"):
        publish(store, [asset["asset_id"]])
    assert "../outside.txt" in index_path.read_text()


def test_linked_library_is_rejected(tmp_path):
    store = AssetStore(tmp_path / "store")
    asset = store.create_sprite(SpriteRequest())
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (store.root / "library").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable")
    with pytest.raises(ValueError, match="link|escapes"):
        publish(store, [asset["asset_id"]])
    assert not list(outside.iterdir())


@pytest.mark.parametrize("ids", [[], ["../bad"], ["a_" + "0" * 32] * 201])
def test_selection_is_bounded(tmp_path, ids):
    with pytest.raises(ValueError):
        publish(AssetStore(tmp_path), ids)


@pytest.mark.parametrize("value", ["CON", "nul", "same name", "...", "日本語"])
def test_safe_names_keep_distinct_assets(tmp_path, value):
    store = AssetStore(tmp_path)
    first = store.create_sprite(SpriteRequest())
    second = store.create_sprite(SpriteRequest())
    for asset in (first, second):
        Catalog(tmp_path).update_asset_label(asset["asset_id"], value)
    output = publish(store, [first["asset_id"], second["asset_id"]])
    folders = [entry["folder"] for entry in output["assets"]]
    assert len(set(name.casefold() for name in folders)) == 2
    assert all(not name.endswith((".", " ")) for name in folders)
    assert all(len(name) <= 80 for name in folders)


def test_animation_paths_remain_usable_and_playback_starts_stopped(tmp_path):
    store = AssetStore(tmp_path)
    asset = store.create_sprite(SpriteRequest(template="knight"))
    store.generate_animation(AnimationRequest(asset_id=asset["asset_id"], motion="idle"))
    output = publish(store, [asset["asset_id"]])
    root = Path(output["gallery_path"]).parent
    entry = output["assets"][0]
    folder = root / entry["folder"] / entry["animations"][0]["folder"]
    manifest = json.loads((folder / "manifest.json").read_text())
    assert all((folder / frame["file"]).is_file() for frame in manifest["frames"])
    html = Path(output["gallery_path"]).read_text(encoding="utf-8")
    assert 'aria-pressed="false"' in html
    assert "data-gif=" in html
    assert "<img" in html


def test_all_conflicts_checked_before_any_managed_file_changes(tmp_path):
    store = AssetStore(tmp_path)
    first = store.create_sprite(SpriteRequest(description="One"))
    second = store.create_sprite(SpriteRequest(description="Two"))
    output = publish(store, [first["asset_id"], second["asset_id"]])
    root = Path(output["gallery_path"]).parent
    initial = (root / "index.json").read_bytes()
    bad = root / output["assets"][1]["folder"] / "sprite.png"
    bad.write_bytes(b"keep me")
    Catalog(tmp_path).update_asset_label(first["asset_id"], "Changed name")
    with pytest.raises(ValueError, match="modified|conflict"):
        publish(store, [first["asset_id"], second["asset_id"]])
    assert (root / "index.json").read_bytes() == initial
    assert bad.read_bytes() == b"keep me"


def test_oversized_or_malformed_index_fails_without_writing(tmp_path):
    store = AssetStore(tmp_path)
    asset = store.create_sprite(SpriteRequest())
    output = publish(store, [asset["asset_id"]])
    index = Path(output["index_path"])
    for raw in (b"[]", b"{", b"x" * (8 * 1024 * 1024 + 1)):
        index.write_bytes(raw)
        with pytest.raises(ValueError, match="Invalid|limit|large"):
            publish(store, [asset["asset_id"]])
        assert index.read_bytes() == raw


def test_regular_file_parent_conflict_preserves_all_managed_files(tmp_path):
    store = AssetStore(tmp_path)
    first = store.create_sprite(SpriteRequest(description="One"))
    second = store.create_sprite(SpriteRequest(description="Two"))
    output = publish(store, [first["asset_id"]])
    root = Path(output["gallery_path"]).parent
    occupied = root / ("two--" + second["asset_id"][2:10])
    occupied.write_bytes(b"user file instead of directory")
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    Catalog(tmp_path).update_asset_label(first["asset_id"], "Renamed")
    with pytest.raises(ValueError, match="conflict|directory"):
        publish(store, [first["asset_id"], second["asset_id"]])
    assert before == {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


def test_animation_manifest_changed_after_validation_is_not_published(tmp_path, monkeypatch):
    store = AssetStore(tmp_path)
    asset = store.create_sprite(SpriteRequest(template="knight"))
    animation = store.generate_animation(
        AnimationRequest(asset_id=asset["asset_id"], motion="idle")
    )
    original_validate = store.validate_animation

    def changed_after_validation(identifier):
        result = original_validate(identifier)
        path = animation["manifest_path"]
        manifest = json.loads(path.read_text())
        manifest["frames"][0]["duration_ms"] += 10
        path.write_text(json.dumps(manifest))
        return result

    monkeypatch.setattr(store, "validate_animation", changed_after_validation)
    with pytest.raises(ValueError, match="changed|validation"):
        publish(store, [asset["asset_id"]])
    assert not (store.root / "library" / "index.json").exists()


@pytest.mark.parametrize("interrupted", [False, True])
def test_failed_index_commit_is_recoverable(tmp_path, monkeypatch, interrupted):
    import os

    from gensprite_mcp import library

    store = AssetStore(tmp_path)
    asset = store.create_sprite(SpriteRequest(description="Before"))
    output = publish(store, [asset["asset_id"]])
    root = Path(output["gallery_path"]).parent
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    Catalog(tmp_path).update_asset_label(asset["asset_id"], "After")
    original_replace = os.replace
    triggered = False

    def fail_index(source, destination):
        nonlocal triggered
        if Path(destination) == root / "index.json" and not triggered:
            triggered = True
            if interrupted:
                raise KeyboardInterrupt("simulated process interruption")
            raise OSError("simulated index replacement failure")
        return original_replace(source, destination)

    monkeypatch.setattr(library.os, "replace", fail_index)
    with pytest.raises((KeyboardInterrupt, OSError)):
        publish(store, [asset["asset_id"]])
    monkeypatch.setattr(library.os, "replace", original_replace)
    if not interrupted:
        assert before == {
            str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
        }
    result = publish(store, [asset["asset_id"]])
    assert result["assets"][0]["name"] == "After"
    assert "After" in Path(result["gallery_path"]).read_text(encoding="utf-8")


def test_recovery_never_replaces_manual_changes(tmp_path, monkeypatch):
    import os

    from gensprite_mcp import library

    store = AssetStore(tmp_path)
    asset = store.create_sprite(SpriteRequest(description="Before"))
    output = publish(store, [asset["asset_id"]])
    root = Path(output["gallery_path"]).parent
    Catalog(tmp_path).update_asset_label(asset["asset_id"], "After")
    original_replace = os.replace

    def fail_index(source, destination):
        if Path(destination) == root / "index.json":
            raise KeyboardInterrupt("simulated interruption")
        return original_replace(source, destination)

    monkeypatch.setattr(library.os, "replace", fail_index)
    with pytest.raises(KeyboardInterrupt):
        publish(store, [asset["asset_id"]])
    monkeypatch.setattr(library.os, "replace", original_replace)
    changed = root / output["assets"][0]["folder"] / "asset.json"
    changed.write_bytes(b"manual changes after interruption")
    with pytest.raises(ValueError, match="modified|conflict"):
        publish(store, [asset["asset_id"]])
    assert changed.read_bytes() == b"manual changes after interruption"


def test_python311_junction_is_rejected_before_publication(tmp_path, monkeypatch):
    import os
    import subprocess

    if os.name != "nt":
        pytest.skip("Windows junction regression")
    store = AssetStore(tmp_path / "store")
    asset = store.create_sprite(SpriteRequest())
    outside = tmp_path / "outside"
    outside.mkdir()
    link = store.root / "library"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        check=False,
    )
    if created.returncode:
        pytest.skip("Cannot create a directory junction")
    monkeypatch.delattr(Path, "is_junction", raising=False)
    try:
        with pytest.raises(ValueError, match="link|junction|reparse"):
            publish(store, [asset["asset_id"]])
        assert not list(outside.iterdir())
    finally:
        link.rmdir()


@pytest.mark.parametrize("phase", ["first", "rollback", "committed"])
def test_publication_recovers_at_other_transaction_boundaries(tmp_path, monkeypatch, phase):
    import os

    from gensprite_mcp import library

    store = AssetStore(tmp_path)
    asset = store.create_sprite(SpriteRequest(description="Before"))
    if phase != "first":
        publish(store, [asset["asset_id"]])
        Catalog(tmp_path).update_asset_label(asset["asset_id"], "After")
    root = store.root / "library"
    original_replace = os.replace
    replaced = False

    def interrupt(source, destination):
        nonlocal replaced
        if phase == "committed" and Path(source).name == "publish-transaction":
            raise KeyboardInterrupt("interruption after committing the new index")
        if phase in ("first", "rollback") and Path(destination) == root / "index.json":
            replaced = True
            raise OSError("index failure")
        if phase == "rollback" and replaced and Path(destination).name == "asset.json":
            raise OSError("rollback temporarily unavailable")
        return original_replace(source, destination)

    monkeypatch.setattr(library.os, "replace", interrupt)
    with pytest.raises((KeyboardInterrupt, OSError)):
        publish(store, [asset["asset_id"]])
    monkeypatch.setattr(library.os, "replace", original_replace)
    result = publish(store, [asset["asset_id"]])
    assert result["assets"][0]["name"] == ("Before" if phase == "first" else "After")
    index = json.loads(Path(result["index_path"]).read_text())
    import hashlib

    for relative, digest in index["files"].items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest


def test_recovery_rechecks_each_target_before_rollback(tmp_path, monkeypatch):
    import os

    from gensprite_mcp import library

    store = AssetStore(tmp_path)
    first = store.create_sprite(SpriteRequest(description="First"))
    second = store.create_sprite(SpriteRequest(description="Second"))
    output = publish(store, [first["asset_id"], second["asset_id"]])
    root = Path(output["gallery_path"]).parent
    for asset in (first, second):
        Catalog(tmp_path).update_asset_label(asset["asset_id"], "New label")
    original_replace = os.replace

    def interrupt(source, destination):
        if Path(destination) == root / "index.json":
            raise KeyboardInterrupt("interrupt")
        return original_replace(source, destination)

    monkeypatch.setattr(library.os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        publish(store, [first["asset_id"], second["asset_id"]])
    monkeypatch.setattr(library.os, "replace", original_replace)
    changed = root / output["assets"][1]["folder"] / "asset.json"
    replace_payload = library._replace_payload
    touched = False

    def edit_during_recovery(*args):
        nonlocal touched
        replace_payload(*args)
        if not touched:
            changed.write_bytes(b"manual concurrent edit")
            touched = True

    monkeypatch.setattr(library, "_replace_payload", edit_during_recovery)
    with pytest.raises(ValueError, match="modified|conflict"):
        publish(store, [first["asset_id"], second["asset_id"]])
    assert changed.read_bytes() == b"manual concurrent edit"


@pytest.mark.parametrize("length", [0, 25])
def test_partial_swap_from_interrupted_write_is_recoverable(tmp_path, monkeypatch, length):
    from gensprite_mcp import library

    store = AssetStore(tmp_path)
    asset = store.create_sprite(SpriteRequest(description="Before"))
    publish(store, [asset["asset_id"]])
    Catalog(tmp_path).update_asset_label(asset["asset_id"], "After")
    write = library._durable_write

    def partial_swap(path, content):
        if path.name == "swap.tmp" and b'"files":' in content:
            path.write_bytes(content[:length])
            raise KeyboardInterrupt("partial write")
        return write(path, content)

    monkeypatch.setattr(library, "_durable_write", partial_swap)
    with pytest.raises(KeyboardInterrupt):
        publish(store, [asset["asset_id"]])
    monkeypatch.setattr(library, "_durable_write", write)
    result = publish(store, [asset["asset_id"]])
    assert result["assets"][0]["name"] == "After"


def test_edit_after_verify_is_not_snapshotted_as_owned_content(tmp_path, monkeypatch):
    from gensprite_mcp import library

    store = AssetStore(tmp_path)
    asset = store.create_sprite(SpriteRequest(description="Before"))
    output = publish(store, [asset["asset_id"]])
    root = Path(output["gallery_path"]).parent
    changed = root / output["assets"][0]["folder"] / "asset.json"
    index_before = (root / "index.json").read_bytes()
    Catalog(tmp_path).update_asset_label(asset["asset_id"], "After")
    commit = library._commit

    def edit_before_snapshot(*args):
        changed.write_bytes(b"user change after verify")
        return commit(*args)

    monkeypatch.setattr(library, "_commit", edit_before_snapshot)
    with pytest.raises(ValueError, match="modified|conflict"):
        publish(store, [asset["asset_id"]])
    assert changed.read_bytes() == b"user change after verify"
    assert (root / "index.json").read_bytes() == index_before
    assert not (root / "publish-transaction").exists()
