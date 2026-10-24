"""Named delivery copies of immutable assets with a local file:// gallery."""

import hashlib
import html
import io
import json
import os
import re
import stat
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from uuid import uuid4

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .assets import AssetStore
from .catalog import Catalog
from .models import AnimationManifest

MAX_ASSETS = 1000
MAX_FILES = 20000
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_LIBRARY_BYTES = 256 * 1024 * 1024
Folder = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}--[0-9a-f]{8,32}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Duration = Annotated[int, Field(ge=10, le=10000)]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Motion(_Record):
    animation_id: Annotated[str, Field(pattern=r"^n_[0-9a-f]{32}$")]
    folder: Folder
    motion: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    durations_ms: Annotated[list[Duration], Field(min_length=1, max_length=16)]
    loop: bool


class _Asset(_Record):
    asset_id: Annotated[str, Field(pattern=r"^a_[0-9a-f]{32}$")]
    folder: Folder
    name: Annotated[str, Field(min_length=1, max_length=200)]
    width: Annotated[int, Field(ge=8, le=256)]
    height: Annotated[int, Field(ge=8, le=256)]
    animations: Annotated[list[_Motion], Field(max_length=200)]


class _Index(_Record):
    schema_version: Literal[1] = 1
    assets: Annotated[list[_Asset], Field(max_length=MAX_ASSETS)]
    files: Annotated[dict[str, Digest], Field(max_length=MAX_FILES)]


class _Change(_Record):
    old: Digest | None
    new: Digest


class _Journal(_Record):
    schema_version: Literal[1] = 1
    changes: Annotated[dict[str, _Change], Field(min_length=1, max_length=MAX_FILES + 1)]


def _json(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _path(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if (
        not parts
        or len(relative) > 240
        or "\\" in relative
        or any(not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", part) for part in parts)
        or PurePosixPath(relative).as_posix() != relative
    ):
        raise ValueError(f"Unsafe library path: {relative!r}")
    target = root.joinpath(*parts)
    candidate = target
    while True:
        try:
            attributes = getattr(candidate.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            attributes = 0
        if candidate.is_symlink() or attributes & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
        ):
            raise ValueError("Library links, junctions and reparse points are not allowed")
        if candidate != target and candidate.exists() and not candidate.is_dir():
            raise ValueError("Library destination conflict: parent is not a directory")
        if candidate == root:
            break
        candidate = candidate.parent
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Library path escapes the managed root")
    return target


def _read_file(path: Path) -> bytes:
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"Library file missing or exceeds size limit: {path.name}")
    return path.read_bytes()


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _expected(assets: list[_Asset]) -> set[str]:
    files = {"index.html"}
    folders, ids, motion_ids = set(), set(), set()
    for asset in assets:
        if asset.asset_id in ids or asset.folder.casefold() in folders:
            raise ValueError("Invalid library index: duplicate asset IDs or folders")
        ids.add(asset.asset_id)
        folders.add(asset.folder.casefold())
        files.update(
            f"{asset.folder}/{name}" for name in ("sprite.png", "preview.png", "asset.json")
        )
        local_folders = set()
        for motion in asset.animations:
            if (
                motion.animation_id in motion_ids
                or motion.folder.casefold() in local_folders
                or any(duration % 10 for duration in motion.durations_ms)
            ):
                raise ValueError("Invalid library index: duplicate animation or invalid duration")
            motion_ids.add(motion.animation_id)
            local_folders.add(motion.folder.casefold())
            prefix = f"{asset.folder}/{motion.folder}"
            files.update(
                f"{prefix}/{name}" for name in ("preview.gif", "spritesheet.png", "manifest.json")
            )
            files.update(f"{prefix}/{i:03}.png" for i in range(len(motion.durations_ms)))
    return files


def _load_index(root: Path) -> tuple[_Index, bytes | None]:
    path = _path(root, "index.json")
    if not path.exists():
        return _Index(assets=[], files={}), None
    if not path.is_file() or path.stat().st_size > MAX_INDEX_BYTES:
        raise ValueError("Invalid library index: exceeds the 8 MiB limit or is not a file")
    raw = path.read_bytes()
    return _parse_index(root, raw), raw


def _parse_index(root: Path, raw: bytes) -> _Index:
    try:
        index = _Index.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError("Invalid library index; preserve it and restore a valid backup") from exc
    for name in index.files:
        _path(root, name)
    if set(index.files) != _expected(index.assets):
        raise ValueError("Invalid library index: managed file list differs from its assets")
    return index


def _verify(root: Path, files: dict[str, str]) -> dict[str, int]:
    sizes = {}
    for relative, digest in files.items():
        path = _path(root, relative)
        if not path.is_file() or _hash(_read_file(path)) != digest:
            raise ValueError(f"Library file modified or missing; resolve conflict: {relative}")
        sizes[relative] = path.stat().st_size
    if sum(sizes.values()) > MAX_LIBRARY_BYTES:
        raise ValueError("Library exceeds the 256 MiB delivery limit; use a separate asset store")
    return sizes


def _durable_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_payload(root: Path, transaction: Path, relative: str, content: bytes) -> None:
    target = _path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    swap = _path(transaction, "swap.tmp")
    if swap.exists():
        raise ValueError("Publication recovery conflict: unexpected swap file")
    _durable_write(swap, content)
    os.replace(swap, target)


def _journal_files(root: Path, transaction: Path) -> tuple[_Journal, dict[str, str]]:
    raw = _read_file(_path(transaction, "journal.json"))
    try:
        journal = _Journal.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError("Invalid publication journal; preserve it for recovery") from exc
    if "index.json" not in journal.changes:
        raise ValueError("Invalid publication journal: missing index change")
    expected = {"journal.json": _hash(raw)}
    for name, change in journal.changes.items():
        _path(root, name)
        expected[f"after/{name}"] = change.new
        if change.old is not None:
            expected[f"before/{name}"] = change.old
    total = 0
    for name, digest in expected.items():
        content = _read_file(_path(transaction, name))
        total += len(content)
        if _hash(content) != digest:
            raise ValueError(f"Publication recovery conflict: modified backup {name}")
    if total > 2 * MAX_LIBRARY_BYTES + 3 * MAX_INDEX_BYTES:
        raise ValueError("Publication recovery backup exceeds size limits")
    new_index = _parse_index(root, _read_file(_path(transaction, "after/index.json")))
    previous = journal.changes["index.json"].old
    old_index = (
        _parse_index(root, _read_file(_path(transaction, "before/index.json")))
        if previous is not None
        else _Index(assets=[], files={})
    )
    if not set(old_index.files) <= set(new_index.files):
        raise ValueError("Invalid publication journal: existing files were removed")
    changes = {
        name for name, digest in new_index.files.items() if old_index.files.get(name) != digest
    } | {"index.json"}
    if set(journal.changes) != changes:
        raise ValueError("Invalid publication journal: mismatched changed files")
    for name in changes - {"index.json"}:
        change = journal.changes[name]
        if change.old != old_index.files.get(name) or change.new != new_index.files[name]:
            raise ValueError("Invalid publication journal: mismatched payload hashes")
    allowed_dirs = {
        parent.as_posix()
        for name in expected
        for parent in PurePosixPath(name).parents
        if parent.as_posix() != "."
    }
    pending = [transaction]
    while pending:
        directory = pending.pop()
        for child in directory.iterdir():
            name = child.relative_to(transaction).as_posix()
            path = _path(transaction, name)
            if path.is_dir() and name in allowed_dirs:
                pending.append(path)
            elif path.is_file() and name in expected:
                continue
            elif name == "swap.tmp" and path.is_file():
                scratch = _read_file(path)
                payloads = [value for value in expected if value.startswith(("before/", "after/"))]
                if not any(
                    _read_file(_path(transaction, value)).startswith(scratch) for value in payloads
                ):
                    raise ValueError("Publication recovery conflict: modified swap file")
                expected[name] = _hash(scratch)
            else:
                raise ValueError(f"Publication recovery conflict: unmanaged staging path {name}")
    return journal, expected


def _finish_transaction(root: Path, transaction: Path, expected: dict[str, str]) -> None:
    # Detach completed recovery atomically; interrupted cleanup cannot block the next batch.
    detached = _path(root, "completed-" + uuid4().hex)
    os.replace(transaction, detached)
    for name, digest in expected.items():
        path = _path(detached, name)
        if _hash(_read_file(path)) != digest:
            raise ValueError("Completed publication backup changed; preserve it for inspection")
        path.unlink()
    directories = {
        parent
        for name in expected
        for parent in PurePosixPath(name).parents
        if parent.as_posix() != "."
    }
    for relative in sorted(directories, key=lambda value: len(value.parts), reverse=True):
        _path(detached, relative.as_posix()).rmdir()
    detached.rmdir()


def _recover(root: Path) -> None:
    transaction = _path(root, "publish-transaction")
    if not transaction.exists():
        return
    if not transaction.is_dir():
        raise ValueError("Publication recovery conflict: transaction must be a directory")
    journal, expected = _journal_files(root, transaction)
    index = _path(root, "index.json")
    index_digest = _hash(_read_file(index)) if index.exists() else None
    committed = index_digest == journal.changes["index.json"].new
    # Preflight every destination before restoring anything; user changes are preserved.
    for name, change in journal.changes.items():
        target = _path(root, name)
        current = _hash(_read_file(target)) if target.exists() else None
        allowed = {change.new} if committed else {change.old, change.new}
        if current not in allowed:
            raise ValueError(f"Publication recovery conflict: modified destination {name}")
    swap = _path(transaction, "swap.tmp")
    if swap.exists():
        swap.unlink()  # Its digest was checked against known journal payloads above.
        expected.pop("swap.tmp")
    if not committed:
        names = [name for name in journal.changes if name != "index.json"] + ["index.json"]
        for name in names:
            change = journal.changes[name]
            target = _path(root, name)
            current = _hash(_read_file(target)) if target.exists() else None
            if current == change.old:
                continue
            if current != change.new:
                raise ValueError(f"Publication recovery conflict: modified destination {name}")
            if change.old is None:
                target.unlink()
            else:
                content = _read_file(_path(transaction, f"before/{name}"))
                _replace_payload(root, transaction, name, content)
    _finish_transaction(root, transaction, expected)


def _commit(root: Path, pending: dict[str, bytes], original_index: bytes | None) -> None:
    index_path = _path(root, "index.json")
    if (index_path.read_bytes() if index_path.exists() else None) != original_index:
        raise ValueError("Library index modified before staging; resolve conflict and retry")
    owned = _parse_index(root, original_index).files if original_index is not None else {}
    _verify(root, owned)
    changed = {}
    previous = {}
    for name, content in pending.items():
        target = _path(root, name)
        old = _read_file(target) if target.exists() else None
        expected = (
            (_hash(original_index) if original_index is not None else None)
            if name == "index.json"
            else owned.get(name)
        )
        if (_hash(old) if old is not None else None) != expected:
            raise ValueError(f"Library destination modified before staging; conflict: {name}")
        if old != content:
            changed[name] = _Change(old=_hash(old) if old is not None else None, new=_hash(content))
            previous[name] = old
    if not changed:
        return
    journal = _Journal(changes=changed)
    transaction = _path(root, "publish-transaction")
    if transaction.exists():
        raise ValueError("Publication recovery conflict: existing transaction")
    with tempfile.TemporaryDirectory(prefix="stage-", dir=root) as temporary:
        stage = Path(temporary)
        for name in changed:
            _durable_write(_path(stage, f"after/{name}"), pending[name])
            if previous[name] is not None:
                _durable_write(_path(stage, f"before/{name}"), previous[name])
        _durable_write(_path(stage, "journal.json"), _json(journal.model_dump()))
        current_index = _path(root, "index.json")
        if (current_index.read_bytes() if current_index.exists() else None) != original_index:
            raise ValueError("Library index changed during staging; retry after resolving conflict")
        _verify(root, owned)
        for name, change in changed.items():
            target = _path(root, name)
            digest = _hash(_read_file(target)) if target.exists() else None
            if digest != change.old:
                raise ValueError(f"Library destination modified during staging: {name}")
        os.replace(stage, transaction)
    try:
        names = [name for name in changed if name != "index.json"] + ["index.json"]
        for name in names:
            target = _path(root, name)
            digest = _hash(_read_file(target)) if target.exists() else None
            if digest != changed[name].old:
                raise ValueError(f"Library destination modified during publication: {name}")
            _replace_payload(root, transaction, name, pending[name])
    except OSError:
        _recover(root)
        raise
    _recover(root)


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:40].rstrip("-") or "sprite"
    if re.fullmatch(r"con|prn|aux|nul|com[1-9]|lpt[1-9]", slug):
        slug = "asset-" + slug
    return slug


def _folder(text: str, identifier: str, occupied: set[str]) -> str:
    slug, digest = _slug(text), identifier[2:]
    for length in range(8, 33, 4):
        value = f"{slug}--{digest[:length]}"
        if value.casefold() not in occupied:
            occupied.add(value.casefold())
            return value
    raise ValueError("Library naming conflict; choose another label")


def _preview(raw: bytes) -> bytes:
    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGBA")
        scale = max(1, min(8, 256 // max(image.size)))
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    board = Image.new("RGBA", (256, 256), "#1C2834")
    draw = ImageDraw.Draw(board)
    for y in range(0, 256, 16):
        for x in range(0, 256, 16):
            if (x // 16 + y // 16) % 2:
                draw.rectangle((x, y, x + 15, y + 15), fill="#263442")
    board.alpha_composite(image, ((256 - image.width) // 2, (256 - image.height) // 2))
    output = io.BytesIO()
    board.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def _gallery(assets: list[_Asset]) -> bytes:
    cards = []
    for asset in assets:
        folder = asset.folder
        animations = []
        for i, motion in enumerate(asset.animations):
            prefix = f"{folder}/{motion.folder}"
            image_id = f"animation-{asset.asset_id}-{i}"
            animations.append(
                '<div class="motion"><div class="motion-heading"><strong>'
                + html.escape(motion.motion.replace("_", " ").title())
                + f"</strong><span>{len(motion.durations_ms)} frames / "
                + f"{sum(motion.durations_ms)} ms</span></div>"
                + f'<img id="{image_id}" class="animation" src="{prefix}/000.png" '
                + f'data-still="{prefix}/000.png" data-gif="{prefix}/preview.gif" '
                + f'alt="{html.escape(asset.name, quote=True)} motion preview, stopped" '
                + 'width="192" height="192" loading="lazy">'
                + '<button type="button" class="play" aria-pressed="false" '
                + f'aria-controls="{image_id}">Play preview</button>'
                + f'<a href="{prefix}/spritesheet.png">Sprite sheet</a> '
                + f'<a href="{prefix}/manifest.json">Timing and metadata</a></div>'
            )
        cards.append(
            '<article class="card"><div class="card-main">'
            + f'<img class="thumbnail" src="{folder}/preview.png" '
            + f'alt="{html.escape(asset.name, quote=True)}" width="256" height="256" '
            + 'loading="lazy"><div class="details"><p class="eyebrow">SPRITE</p><h2>'
            + html.escape(asset.name)
            + f'</h2><p class="dimensions">{asset.width} &times; {asset.height} pixels</p>'
            + f'<a class="primary-link" href="{folder}/sprite.png">Open native PNG</a> '
            + f'<a href="{folder}/asset.json">Asset details</a>'
            + f'<p class="identifier">{asset.asset_id}</p></div></div>'
            + (
                f"<details><summary>{len(animations)} animation previews</summary>"
                + '<div class="motions">'
                + "".join(animations)
                + "</div></details>"
                if animations
                else ""
            )
            + "</article>"
        )
    template = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><title>GenSprite | Asset library</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#10161e;color:#edf2f8;font:16px/1.5 system-ui,sans-serif}
main{max-width:1220px;margin:auto;padding:44px 24px 80px}header{border-bottom:1px solid #344250;padding-bottom:32px}
.brand{letter-spacing:.16em;font-size:.8rem;color:#7fe0c1;font-weight:700}h1{font-size:clamp(2rem,5vw,3rem);line-height:1.1;margin:18px 0 12px}
.intro,.dimensions,.identifier,.motion-heading span{color:#a8b8c9}.intro{max-width:680px;margin-bottom:26px}
.search{max-width:520px}label{display:block;font-size:.85rem;margin-bottom:8px;font-weight:600}
input{width:100%;padding:13px 15px;background:#192430;border:1px solid #536678;border-radius:8px;color:inherit;font:inherit}
#count{font-size:.85rem;color:#a8b8c9;margin:14px 0 0}.grid{display:grid;gap:22px;margin-top:30px}
.card{background:#19232f;border:1px solid #344454;border-radius:12px;overflow:hidden}.card-main{display:flex;gap:30px;padding:22px}
.thumbnail{width:192px;height:192px;object-fit:contain;border-radius:6px;flex-shrink:0;background:#263442;image-rendering:pixelated}
.details{padding-top:8px;min-width:0}.eyebrow{font-size:.7rem;letter-spacing:.16em;color:#7fe0c1;margin:0}h2{font-size:1.6rem;line-height:1.25;margin:10px 0;overflow-wrap:anywhere}
a{color:#8ce3cb;text-underline-offset:4px;font-size:.9rem}.primary-link{display:inline-block;margin-right:18px}
.identifier{font:11px/1.5 ui-monospace,monospace;margin-top:20px;overflow-wrap:anywhere}.dimensions{margin:8px 0 20px}
details{border-top:1px solid #344454}summary{padding:16px 22px;cursor:pointer;font-weight:600;color:#ccdae7}
.motions{display:flex;gap:20px;padding:2px 22px 24px;flex-wrap:wrap}.motion{background:#101a24;border:1px solid #344454;border-radius:8px;padding:16px;display:flex;flex-direction:column;gap:12px;width:260px}
.motion-heading{display:flex;flex-direction:column}.motion-heading span{font-size:.75rem}.animation{image-rendering:pixelated;object-fit:contain;background:repeating-conic-gradient(#1c2834 0 25%,#263442 0 50%) 0/24px 24px;width:192px;height:192px;margin:auto}
button{padding:10px 15px;color:#101820;background:#8ce3cb;border:0;border-radius:6px;font:600 .85rem system-ui;cursor:pointer}
:focus-visible{outline:3px solid #ffd67a;outline-offset:4px}#empty{padding:40px 0;color:#a8b8c9}[hidden]{display:none!important}
footer{margin-top:30px;color:#a8b8c9;font-size:.8rem} @media(max-width:620px){main{padding:28px 16px}.card-main{flex-direction:column;gap:12px}.thumbnail{align-self:center}.details{padding:0}.motion{width:100%}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}button{transition:none}}
</style></head><body><main><header><div class="brand">GENSPRITE / LOCAL LIBRARY</div>
<h1>Your sprites, ready to find.</h1><p class="intro">Finished artwork and animation previews in one place. Open native files below. Previews are enlarged with crisp pixels; your original files keep their native size.</p>
<div class="search"><label for="search">Find an asset</label><input id="search" type="search" placeholder="Search names or asset IDs" autocomplete="off"></div>
<p id="count" aria-live="polite">__COUNT__ assets</p></header><section class="grid" aria-label="Published assets">__CARDS__</section><p id="empty" hidden>No assets match your search.</p>
<footer>Local delivery copies. Revise original assets through GenSprite, then publish again. Animation previews repeat for inspection; manifests preserve intended playback.</footer></main>
<script>
const search=document.getElementById('search'),cards=[...document.querySelectorAll('.card')];
function stop(button){const image=document.getElementById(button.getAttribute('aria-controls'));image.src=image.dataset.still;image.alt=image.alt.replace(/, (playing|stopped)$/,', stopped');button.setAttribute('aria-pressed','false');button.textContent='Play preview';}
function stopAll(){document.querySelectorAll('.play[aria-pressed="true"]').forEach(stop);}
search.addEventListener('input',()=>{const query=search.value.trim().toLocaleLowerCase();let visible=0;cards.forEach(card=>{card.hidden=!card.textContent.toLocaleLowerCase().includes(query);if(!card.hidden)visible++;else card.querySelectorAll('.play[aria-pressed="true"]').forEach(stop);});document.getElementById('count').textContent=visible+' of '+cards.length+' assets';document.getElementById('empty').hidden=visible!==0;});
document.querySelectorAll('.play').forEach(button=>button.addEventListener('click',()=>{if(button.getAttribute('aria-pressed')==='true'){stop(button);return;}stopAll();const image=document.getElementById(button.getAttribute('aria-controls'));image.src=image.dataset.gif;image.alt=image.alt.replace(/, (playing|stopped)$/,', playing');button.setAttribute('aria-pressed','true');button.textContent='Stop preview';}));
document.querySelectorAll('details').forEach(details=>details.addEventListener('toggle',()=>{if(!details.open)details.querySelectorAll('.play[aria-pressed="true"]').forEach(stop);}));
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopAll();});
const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');reduced.addEventListener('change',event=>{if(event.matches)stopAll();});
</script></body></html>"""  # noqa: E501
    return (
        template.replace("__COUNT__", str(len(assets)))
        .replace("__CARDS__", "\n".join(cards))
        .encode("utf-8")
    )


def _animations(store: AssetStore, catalog: Catalog, selected: set[str]) -> dict:
    candidates, truncated = catalog._discover("animations", "n")
    if truncated:
        raise ValueError("Animation discovery limit reached; publication would be incomplete")
    animations = {identifier: [] for identifier in selected}
    for _, identifier in candidates:
        path = store._path("animations", identifier, "manifest.json")
        manifest = store._read(path, AnimationManifest)
        if manifest.animation_id != identifier:
            raise ValueError("Animation manifest ID differs from its source directory")
        if manifest.source_asset_id not in selected:
            continue
        if store.validate_animation(identifier)["errors"]:
            raise ValueError(f"Animation source validation failed: {identifier}")
        animations[manifest.source_asset_id].append(manifest)
    if any(len(values) > 200 for values in animations.values()):
        raise ValueError("Library supports at most 200 animations per master")
    return animations


def build_asset_library(store: AssetStore, asset_ids: list[str]) -> dict:
    """Publish finished masters and animations without changing canonical assets.

    One batch accepts 1..200 distinct sprite IDs. The persistent library holds at most
    1,000 masters / 20,000 managed files / 256 MiB, with an 8 MiB index. A managed file
    edited or removed outside GenSprite is a conflict, never silently replaced.
    """
    if (
        not isinstance(asset_ids, list)
        or not 1 <= len(asset_ids) <= 200
        or any(not isinstance(i, str) or not re.fullmatch(r"a_[0-9a-f]{32}", i) for i in asset_ids)
        or len(set(asset_ids)) != len(asset_ids)
    ):
        raise ValueError("Select 1..200 distinct generated a_ sprite IDs")
    root = store.root / "library"
    _path(root, "index.json")
    if root.exists() and not root.is_dir():
        raise ValueError("Library destination must be a directory")
    root.mkdir(parents=True, exist_ok=True)
    lock = _path(root, "publish.lock")
    # A single local server owns the store; reject overlapping publication calls as well.
    try:
        handle = lock.open("xb")
    except FileExistsError as exc:
        raise ValueError(
            "Library publication is active, or publish.lock is stale after an interruption. "
            "If no process is using this store, remove library/publish.lock and retry recovery."
        ) from exc
    try:
        with handle:
            _recover(root)
            return _publish(store, root, asset_ids)
    finally:
        lock.unlink()


def _publish(store: AssetStore, root: Path, asset_ids: list[str]) -> dict:
    index, original_index = _load_index(root)
    sizes = _verify(root, index.files)
    records = {asset.asset_id: asset for asset in index.assets}
    if len(set(records) | set(asset_ids)) > MAX_ASSETS:
        raise ValueError("Library capacity is 1,000 masters; use a separate asset store")
    occupied = {asset.folder.casefold() for asset in records.values()}
    pending = {}
    catalog = Catalog(store.root)
    discovered = _animations(store, catalog, set(asset_ids))
    selected = []
    for identifier in asset_ids:
        info = catalog.get_asset_metadata(identifier)
        if info["validation"]["errors"]:
            raise ValueError(f"Source asset validation failed: {identifier}")
        description = info["description"].splitlines()
        name = (info["label"] or (description[0][:100] if description else "Sprite")).strip()
        name = name or "Sprite"
        previous = records.get(identifier)
        folder = previous.folder if previous else _folder(name, identifier, occupied)
        raw = _read_file(store._path("generated", identifier, "sprite.png"))
        if _hash(raw) != info["source_sha256"]:
            raise ValueError("Source sprite changed during publication")
        pending[f"{folder}/sprite.png"] = raw
        pending[f"{folder}/preview.png"] = _preview(raw)
        animations = []
        old_motions = (
            {motion.animation_id: motion for motion in previous.animations} if previous else {}
        )
        motion_folders = {motion.folder.casefold() for motion in old_motions.values()}
        for manifest in sorted(discovered[identifier], key=lambda value: value.animation_id):
            animation_id = manifest.animation_id
            manifest_path = store._path("animations", animation_id, "manifest.json")
            motion_folder = (
                old_motions[animation_id].folder
                if animation_id in old_motions
                else _folder(manifest.motion, animation_id, motion_folders)
            )
            prefix = f"{folder}/{motion_folder}"
            for filename, digest in (
                (manifest.preview, manifest.preview_sha256),
                (manifest.spritesheet, manifest.spritesheet_sha256),
                *((frame.file, frame.source_sha256) for frame in manifest.frames),
            ):
                content = _read_file(store._path("animations", animation_id, filename))
                if _hash(content) != digest:
                    raise ValueError("Animation source changed during publication")
                pending[f"{prefix}/{filename}"] = content
            manifest_raw = _read_file(manifest_path)
            if AnimationManifest.model_validate_json(manifest_raw) != manifest:
                raise ValueError("Animation manifest changed during publication")
            pending[f"{prefix}/manifest.json"] = manifest_raw
            animations.append(
                _Motion(
                    animation_id=animation_id,
                    folder=motion_folder,
                    motion=manifest.motion,
                    durations_ms=[frame.duration_ms for frame in manifest.frames],
                    loop=manifest.loop,
                )
            )
        entry = _Asset(
            asset_id=identifier,
            folder=folder,
            name=name,
            width=info["width"],
            height=info["height"],
            animations=animations,
        )
        pending[f"{folder}/asset.json"] = _json(entry.model_dump())
        records[identifier] = entry
        selected.append(entry)
    assets = sorted(records.values(), key=lambda value: (value.name.casefold(), value.asset_id))
    pending["index.html"] = _gallery(assets)
    files = dict(index.files)
    for relative, content in pending.items():
        if len(content) > MAX_FILE_BYTES:
            raise ValueError("Library output exceeds the per-file size limit")
        _path(root, relative)
        files[relative] = _hash(content)
    if len(files) > MAX_FILES or set(files) != _expected(assets):
        raise ValueError(
            "Library file capacity reached or animation set changed; preserve existing data"
        )
    total = sum(size for name, size in sizes.items() if name not in pending)
    if total + sum(map(len, pending.values())) > MAX_LIBRARY_BYTES:
        raise ValueError("Library exceeds the 256 MiB delivery limit; use a separate asset store")
    new_index = _json(_Index(assets=assets, files=files).model_dump())
    if len(new_index) > MAX_INDEX_BYTES:
        raise ValueError("Library index exceeds the 8 MiB limit")
    for relative in pending:
        target = _path(root, relative)
        if target.exists() and relative not in index.files:
            raise ValueError(f"Unmanaged library destination conflict: {relative}")
    current_index = _path(root, "index.json")
    if (current_index.read_bytes() if current_index.exists() else None) != original_index:
        raise ValueError("Library index changed during publication; retry after resolving conflict")
    _verify(root, index.files)
    _commit(root, {**pending, "index.json": new_index}, original_index)
    return {
        "gallery_path": str(root / "index.html"),
        "gallery_url": (root / "index.html").as_uri(),
        "index_path": str(root / "index.json"),
        "asset_count": len(assets),
        "assets": [asset.model_dump() for asset in selected],
        "note": "Delivery copies. Revise originals with GenSprite, then publish again.",
    }
