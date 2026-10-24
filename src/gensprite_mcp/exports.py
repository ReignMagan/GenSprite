"""Portable, integrity-checked exports and opt-in project copies; no engine execution."""

import hashlib
import io
import json
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from .assets import AssetStore
from .models import AnimationManifest

TARGETS = ("generic", "phaser", "pixijs", "flame", "godot", "unity", "libgdx", "canvas")
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024
ENGINE_SCOPE = "File integrity only; engine import and runtime were not executed."
DOCS = {
    "godot": "https://docs.godotengine.org/en/stable/classes/class_spriteframes.html",
    "phaser": "https://docs.phaser.io/phaser/concepts/animations",
    "pixijs": "https://pixijs.com/8.x/guides/components/scene-objects/animated-sprite",
    "flame": "https://docs.flame-engine.org/latest/flame/rendering/images.html",
    "unity": "https://docs.unity3d.com/ScriptReference/Sprite.Create.html",
    "libgdx": "https://libgdx.com/wiki/graphics/2d/2d-animation",
    "canvas": "https://developer.mozilla.org/en-US/docs/Web/API/CanvasRenderingContext2D/drawImage",
}


def _json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _id(value: str, prefixes: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(rf"[{prefixes}]_[0-9a-f]{{32}}", value):
        raise ValueError("Invalid ID; use a generated asset, animation or export ID")


def _no_links(path: Path, root: Path) -> None:
    for part in [path, *path.parents]:
        try:
            attributes = getattr(part.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            attributes = 0
        if part.is_symlink() or attributes & 0x400:
            raise ValueError("Symlinks and reparse points are not allowed in export/project paths")
        if part == root:
            return
    raise ValueError("Invalid path outside its root")


def _inside(root: Path, relative: str) -> Path:
    if (not isinstance(relative, str) or not relative or len(relative) > 512
            or "\\" in relative or ":" in relative or "\x00" in relative):
        raise ValueError("Invalid portable relative path")
    parts = relative.split("/")
    if len(parts) > 8 or any(
        part in ("", ".", "..") or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", part)
        or part.endswith(".")
        or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", part.split(".")[0], re.I)
        for part in parts
    ):
        raise ValueError("Invalid portable relative path")
    if PurePosixPath(relative).is_absolute():
        raise ValueError("Invalid absolute path")
    path = root.joinpath(*parts)
    _no_links(path, root)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Invalid path outside its root")
    return path


def _read(path: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"Missing file or file exceeds {limit} bytes: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"File exceeds {limit} bytes: {path.name}")
    return data


def _write_files(directory: Path, payloads: dict[str, bytes], root: Path) -> None:
    """Create a fresh package; remove that package if any write fails."""
    _no_links(directory, root)
    directory.mkdir(parents=True, exist_ok=False)
    try:
        for name, data in payloads.items():
            path = _inside(directory, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path = _inside(directory, name)
            with path.open("xb") as output:
                output.write(data)
            if _digest(_read(path, MAX_PACKAGE_BYTES)) != _digest(data):
                raise ValueError(f"Written file digest mismatch: {name}")
    except BaseException:
        _no_links(directory, root)
        shutil.rmtree(directory)
        raise


class ExportStore:
    def __init__(self, store: AssetStore):
        self.store = store

    def _snapshot(self, asset_ids: list[str]) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
        assets: dict[str, dict[str, Any]] = {}
        payloads: dict[str, bytes] = {}

        def add(asset_id: str) -> None:
            _id(asset_id, "an")
            if asset_id in assets:
                return
            animation = asset_id.startswith("n_")
            kind = "animations" if animation else "generated"
            if animation:
                model = self.store._read(
                    self.store._path(kind, asset_id, "manifest.json"), AnimationManifest,
                )
                report = self.store.validate_animation(asset_id)
            else:
                model = self.store._manifest(asset_id)
                report = self.store.validate_sprite(asset_id)
            if report["technical_status"] != "passed":
                raise ValueError(f"Source validation failed for {asset_id}: {report['errors']}")
            manifest = model.model_dump(mode="json")
            if animation:
                add(manifest["source_asset_id"])
            prefix = f"sources/{asset_id}"
            native_manifest = _json(manifest)
            payloads[f"{prefix}/manifest.json"] = native_manifest
            files = ({frame["file"]: frame["source_sha256"] for frame in manifest["frames"]}
                     if animation else {"sprite.png": manifest["source_sha256"]})
            if animation:
                files[manifest["spritesheet"]] = manifest["spritesheet_sha256"]
                files[manifest["preview"]] = manifest["preview_sha256"]
            for name, expected in files.items():
                # The native store validates models; recheck paths and bytes at the copy boundary.
                data = _read(_inside(self.store.root, f"{kind}/{asset_id}/{name}"))
                if _digest(data) != expected:
                    raise ValueError(f"Source digest changed during export: {asset_id}/{name}")
                payloads[f"{prefix}/{name}"] = data
            canvas = manifest["canvas"]
            frames = ([{**frame, "file": f"{prefix}/{frame['file']}"}
                       for frame in manifest["frames"]] if animation else [{
                           "file": f"{prefix}/sprite.png", "duration_ms": None,
                           "source_sha256": manifest["source_sha256"],
                           "rect": {"x": 0, "y": 0, **canvas},
                       }])
            assets[asset_id] = {
                "asset_id": asset_id, "type": manifest["type"], "canvas": canvas,
                "palette": manifest["palette"], "pivot": manifest["pivot"],
                "source_sha256": manifest["source_sha256"],
                "source_asset_id": manifest.get("source_asset_id"),
                "source_manifest": f"{prefix}/manifest.json",
                "source_manifest_sha256": _digest(native_manifest),
                "image": f"{prefix}/{manifest['spritesheet'] if animation else 'sprite.png'}",
                "frames": frames, "motion": manifest.get("motion", "still"),
                "loop": manifest.get("loop", False), "metadata": manifest.get("metadata", {}),
            }
            if sum(map(len, payloads.values())) > MAX_PACKAGE_BYTES:
                raise ValueError("Export exceeds the 64 MiB package limit")

        for asset_id in asset_ids:
            add(asset_id)
        return list(assets.values()), payloads

    def export_asset(self, asset_id: str, target: str = "generic") -> dict[str, Any]:
        """Export validated original PNGs, portable metadata, ZIP and a target loader example."""
        return self._export(asset_id, [], target)

    def export_godot_character_package(
        self, asset_id: str, animation_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Export Godot 4 SpriteFrames/AtlasTexture resources and a pivot-aware loader."""
        _id(asset_id, "a")
        if animation_ids is not None and (not isinstance(animation_ids, list)
                or len(animation_ids) > 16):
            raise ValueError("Provide at most 16 animation IDs or omit animation_ids")
        for animation_id in animation_ids or []:
            _id(animation_id, "n")
        return self._export(asset_id, animation_ids or [], "godot")

    def export_godot_tileset_package(self, asset_id: str) -> dict[str, Any]:
        """Export a Godot 4 TileSet atlas only when regular tile geometry is recorded."""
        _id(asset_id, "a")
        return self._export(asset_id, [], "godot", tileset=True)

    def _export(
        self, primary: str, extra: list[str], target: str, tileset: bool = False,
    ) -> dict[str, Any]:
        if target not in TARGETS:
            raise ValueError(f"Unsupported export target; choose {', '.join(TARGETS)}")
        assets, payloads = self._snapshot([primary, *extra])
        selected = next(asset for asset in assets if asset["asset_id"] == primary)
        if any(asset["source_asset_id"] != primary for asset in assets
               if asset["asset_id"] in extra):
            raise ValueError("Animation source does not match the requested character asset")
        if target == "godot":
            payloads.update(_godot_tileset(selected) if tileset else _godot_character(assets))
        elif target != "generic":
            name, code = _loader_example(target, selected)
            payloads[name] = code.encode("utf-8")
        contract = {
            "format": "gensprite-import-contract-v1", "target": target,
            "coordinate_origin": "top-left", "duration_unit": "milliseconds",
            "pixel_filter": "nearest", "primary_asset_id": primary, "assets": assets,
            "engine_runtime_verified": False,
        }
        payloads["import.json"] = _json(contract)
        payloads["README.md"] = (
            f"# GenSprite {target} export\n\n"
            "PNG pixels are copied unchanged. import.json is a GenSprite import contract; "
            "source manifests preserve native palette, pivot, frame order and timing. "
            "Coordinates and pivots use the top-left canvas origin. Frame rectangles refer "
            "to the sheet; individual frame PNGs are full canvases. Use nearest filtering.\n\n"
            + ("Godot 4 text resources are supplied. SpriteFrames uses speed=1 and relative "
               "frame durations in seconds. loader.gd applies the pixel pivot as a negative "
               "offset. TileSet packages contain atlas tiles only, without collision/terrain "
               "rules. Keep the package together so relative texture paths resolve.\n\n"
               if target == "godot" else "Loader files are examples for the indicated engine. "
               "Adapt their package base path and attach them to the project. No proprietary "
               "project, prefab, Animator controller or engine binary is generated.\n\n")
            + ("Flame: include the copied folder in pubspec.yaml assets and pass the path "
               "relative to assets/images/ as base.\n\n" if target == "flame" else "")
            + ("LibGDX: dispose loaded Texture objects when finished.\n\n"
               if target == "libgdx" else "")
            + f"Verification: {ENGINE_SCOPE}\n\n"
            + (f"Engine reference: {DOCS[target]}\n" if target in DOCS else "")
        ).encode("utf-8")
        export_id = f"e_{uuid4().hex}"
        manifest = {
            "schema_version": "1.0", "export_id": export_id, "target": target,
            "primary_asset_id": primary, "assets": assets, "status": "ready_for_export",
            "engine_runtime_verified": False, "verification_scope": ENGINE_SCOPE,
            "files": {name: {"sha256": _digest(data), "size": len(data)}
                      for name, data in payloads.items()},
        }
        payloads["export.json"] = _json(manifest)
        if len(payloads["export.json"]) > 1024 * 1024:
            raise ValueError("Export manifest exceeds the 1 MiB limit")
        if any(len(data) > MAX_FILE_BYTES for data in payloads.values()):
            raise ValueError("Export file exceeds the 4 MiB limit")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for name, data in payloads.items():
                output.writestr(name, data)
        payloads["package.zip"] = archive.getvalue()
        if sum(map(len, payloads.values())) > MAX_PACKAGE_BYTES:
            raise ValueError("Export exceeds the 64 MiB package limit including ZIP")
        directory = _inside(self.store.root, f"exports/{export_id}")
        _write_files(directory, payloads, self.store.root)
        return {
            "export_id": export_id, "asset_id": primary, "target": target,
            "directory": str(directory), "manifest_path": str(directory / "export.json"),
            "zip_path": str(directory / "package.zip"), "status": "ready_for_export",
            "engine_runtime_verified": False,
        }

    def _load_export(self, export_id: str) -> tuple[dict[str, Any], dict[str, bytes]]:
        _id(export_id, "e")
        directory = _inside(self.store.root, f"exports/{export_id}")
        raw = _read(_inside(directory, "export.json"), 1024 * 1024)
        try:
            manifest = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid export manifest JSON") from exc
        if (not isinstance(manifest, dict) or manifest.get("export_id") != export_id
                or manifest.get("schema_version") != "1.0"
                or manifest.get("target") not in TARGETS
                or not isinstance(manifest.get("files"), dict)
                or not 1 <= len(manifest["files"]) <= 1024):
            raise ValueError("Invalid export manifest")
        payloads = {"export.json": raw}
        total = len(raw)
        for name, record in manifest["files"].items():
            path = _inside(directory, name)
            if name in ("export.json", "package.zip") or not isinstance(record, dict):
                raise ValueError("Invalid export file inventory")
            size = record.get("size")
            digest = record.get("sha256")
            if (type(size) is not int or not 0 <= size <= MAX_FILE_BYTES
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise ValueError("Invalid export file size/digest")
            data = _read(path)
            if len(data) != size or _digest(data) != digest:
                raise ValueError(f"Export file digest mismatch: {name}")
            payloads[name] = data
            total += len(data)
            if total > MAX_PACKAGE_BYTES:
                raise ValueError("Export exceeds the 64 MiB package limit")
        return manifest, payloads

    @staticmethod
    def _project(project_path: str) -> Path:
        if not isinstance(project_path, str) or not project_path or "\x00" in project_path:
            raise ValueError("Provide an existing project directory")
        path = Path(project_path).absolute()
        if ".." in path.parts:
            raise ValueError("Invalid project path traversal")
        _no_links(path, Path(path.anchor))
        if not path.is_dir():
            raise ValueError("Project directory must already exist")
        return path.resolve()

    def detect_engine(self, project_path: str) -> dict[str, Any]:
        """Inspect bounded project markers without running scripts or modifying the project."""
        root = self._project(project_path)
        engines: list[str] = []
        for filename, engine in [("project.godot", "godot"),
                                 ("ProjectSettings/ProjectVersion.txt", "unity")]:
            if _inside(root, filename).is_file():
                engines.append(engine)
        package = _inside(root, "package.json")
        if package.is_file():
            try:
                data = json.loads(_read(package, 65536))
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError("Invalid package.json project marker") from exc
            if not isinstance(data, dict):
                raise ValueError("Invalid package.json project marker")
            for key, engine in [("phaser", "phaser"), ("pixi.js", "pixijs")]:
                if any(isinstance(data.get(section), dict) and key in data[section]
                       for section in ("dependencies", "devDependencies")):
                    engines.append(engine)
        for filename, pattern, engine in [
            ("pubspec.yaml", r"(?m)^\s*flame\s*:", "flame"),
            ("build.gradle", r"com\.badlogicgames\.gdx|gdxVersion", "libgdx"),
            ("build.gradle.kts", r"com\.badlogicgames\.gdx|gdxVersion", "libgdx"),
        ]:
            path = _inside(root, filename)
            if path.is_file() and re.search(pattern, _read(path, 65536).decode("utf-8")):
                if engine not in engines:
                    engines.append(engine)
        return {"project_path": str(root), "engine": engines[0] if len(engines) == 1
                else "multiple" if engines else "unknown", "engines": engines,
                "detection_scope": "Project markers only; no engine execution"}

    @staticmethod
    def _destination(project: Path, manifest: dict[str, Any]) -> Path:
        parent = {"unity": "Assets/GenSprite", "flame": "assets/images/gensprite",
                  "libgdx": "assets/gensprite", "phaser": "public/gensprite",
                  "pixijs": "public/gensprite", "canvas": "public/gensprite"}.get(
                      manifest["target"], "gensprite")
        return _inside(project, f"{parent}/{manifest['export_id']}")

    def integrate_asset(
        self, export_id: str, project_path: str, execute: bool = False,
    ) -> dict[str, Any]:
        """Plan a project copy; execute=True writes a fresh ID directory without overwrites."""
        if type(execute) is not bool:
            raise ValueError("execute must be a boolean")
        manifest, payloads = self._load_export(export_id)
        project = self._project(project_path)
        destination = self._destination(project, manifest)
        if destination.exists():
            raise ValueError("Integration destination already exists; no files were overwritten")
        result: dict[str, Any] = {
            "export_id": export_id, "project_path": str(project),
            "target": manifest["target"], "destination": str(destination), "executed": False,
            "files": [{"path": name, "destination": str(_inside(destination, name)),
                       "sha256": _digest(data), "size": len(data)}
                      for name, data in payloads.items()],
            "verification_scope": ENGINE_SCOPE,
        }
        if execute:
            _write_files(destination, payloads, project)
            try:
                verification = self.verify_integration(export_id, project_path)
                if not verification["passed"]:
                    raise ValueError(f"Integration verification failed: {verification['errors']}")
            except BaseException:
                _no_links(destination, project)
                shutil.rmtree(destination)
                raise
            result.update(executed=True, verification=verification)
        return result

    def verify_integration(self, export_id: str, project_path: str) -> dict[str, Any]:
        """Compare every copied file against the export; does not run an engine or scripts."""
        manifest, payloads = self._load_export(export_id)
        project = self._project(project_path)
        destination = self._destination(project, manifest)
        errors = []
        for name, data in payloads.items():
            try:
                copied = _read(_inside(destination, name))
                if copied != data:
                    errors.append(f"File digest mismatch: {name}")
            except (ValueError, OSError) as exc:
                errors.append(f"{name}: {exc}")
        return {"export_id": export_id, "destination": str(destination),
                "passed": not errors, "errors": errors, "engine_runtime_verified": False,
                "verification_scope": ENGINE_SCOPE}


def _godot_character(assets: list[dict[str, Any]]) -> dict[str, bytes]:
    animations = [asset for asset in assets if asset["asset_id"].startswith("n_")] or assets[:1]
    frame_count = sum(len(asset["frames"]) for asset in animations)
    lines = [f'[gd_resource type="SpriteFrames" load_steps='
             f'{1 + len(animations) + frame_count} format=3]', ""]
    for i, asset in enumerate(animations):
        lines.append(f'[ext_resource type="Texture2D" path="{asset["image"]}" id="t{i}"]')
    entries = []
    names = set()
    for i, asset in enumerate(animations):
        name = asset["motion"]
        if name in names:
            name = f"{name}_{asset['asset_id']}"
        names.add(name)
        asset["godot_animation_name"] = name
        frames = []
        for j, frame in enumerate(asset["frames"]):
            rect = frame["rect"]
            lines.extend(["", f'[sub_resource type="AtlasTexture" id="f{i}_{j}"]',
                          f'atlas = ExtResource("t{i}")',
                          "region = Rect2({x}, {y}, {width}, {height})".format(**rect)])
            duration = (frame["duration_ms"] or 1000) / 1000
            frames.append(f'{{"duration": {duration}, "texture": SubResource("f{i}_{j}")}}')
        entries.append('{"frames": [' + ", ".join(frames) + '], "loop": '
                       + str(asset["loop"]).lower() + ', "name": &'
                       + json.dumps(name) + ', "speed": 1.0}')
    lines.extend(["", "[resource]", "animations = [" + ",\n".join(entries) + "]", ""])
    pivot = animations[0]["pivot"]
    loader = (
        "extends AnimatedSprite2D\n\nfunc _ready() -> void:\n"
        "\ttexture_filter = CanvasItem.TEXTURE_FILTER_NEAREST\n"
        '\tsprite_frames = load(get_script().resource_path.get_base_dir().path_join('
        '"sprite_frames.tres"))\n'
        "\tcentered = false\n"
        f'\toffset = Vector2(-{pivot["x"]}, -{pivot["y"]})\n'
        f'\tplay(&{json.dumps(animations[0]["godot_animation_name"])})\n'
    )
    return {"sprite_frames.tres": "\n".join(lines).encode(), "loader.gd": loader.encode()}


def _godot_tileset(asset: dict[str, Any]) -> dict[str, bytes]:
    tile = asset["metadata"].get("tileset")
    keys = ("tile_width", "tile_height", "columns", "rows")
    if not isinstance(tile, dict) or any(type(tile.get(key)) is not int or
                                       not 1 <= tile[key] <= 256 for key in keys):
        raise ValueError("Godot tileset requires metadata.tileset regular atlas geometry")
    width, height, columns, rows = (tile[key] for key in keys)
    count = tile.get("tile_count", columns * rows)
    if (type(count) is not int or not 1 <= count <= columns * rows
            or asset["canvas"] != {"width": width * columns, "height": height * rows}):
        raise ValueError("Invalid tileset atlas dimensions or tile_count")
    resource = [
        '[gd_resource type="TileSet" load_steps=3 format=3]', "",
        f'[ext_resource type="Texture2D" path="{asset["image"]}" id="1"]', "",
        '[sub_resource type="TileSetAtlasSource" id="Atlas"]',
        'texture = ExtResource("1")', f"texture_region_size = Vector2i({width}, {height})",
        *[f"{i % columns}:{i // columns}/0 = 0" for i in range(count)], "", "[resource]",
        f"tile_size = Vector2i({width}, {height})", 'sources/0 = SubResource("Atlas")', "",
    ]
    loader = (
        "extends Node\n\nfunc load_tileset() -> TileSet:\n"
        '\treturn load(get_script().resource_path.get_base_dir().path_join("tileset.tres"))\n'
    )
    return {"tileset.tres": "\n".join(resource).encode(), "loader.gd": loader.encode()}


def _loader_example(target: str, asset: dict[str, Any]) -> tuple[str, str]:
    """Small loader examples, with exact per-frame durations retained in the contract."""
    encoded = json.dumps({key: asset[key] for key in
                          ("asset_id", "canvas", "pivot", "frames", "loop")})
    frames = asset["frames"]
    width, height = asset["canvas"]["width"], asset["canvas"]["height"]
    px, py = asset["pivot"]["x"], asset["pivot"]["y"]
    if target == "phaser":
        return "loader.js", (
            f"const asset = {encoded};\n"
            "export function preloadGenSprite(scene, base = '') {\n"
            "  asset.frames.forEach((f, i) => scene.load.image("
            "asset.asset_id + i, base + f.file));\n"
            "}\nexport function createGenSprite(scene, x = 0, y = 0) {\n"
            "  asset.frames.forEach((f, i) => scene.textures.get(asset.asset_id + i)"
            ".setFilter(Phaser.Textures.FilterMode.NEAREST));\n"
            "  const sprite = scene.add.sprite(x, y, asset.asset_id + 0)"
            ".setOrigin(asset.pivot.x / asset.canvas.width, asset.pivot.y / asset.canvas.height);\n"
            "  if (asset.frames.length > 1) {\n"
            "    if (!scene.anims.exists(asset.asset_id)) scene.anims.create({key: asset.asset_id,"
            " frameRate: 1000 / asset.frames[0].duration_ms, repeat: asset.loop ? -1 : 0,"
            " frames: asset.frames.map((f, i) => ({key: asset.asset_id + i,"
            " duration: f.duration_ms}))});\n"
            "    sprite.play(asset.asset_id);\n  }\n  return sprite;\n}\n"
        )
    if target == "pixijs":
        return "loader.js", (
            "import { Assets, AnimatedSprite } from 'pixi.js';\n"
            f"const asset = {encoded};\n"
            "export async function loadGenSprite(base = '') {\n"
            "  const frames = await Promise.all(asset.frames.map(async f => {\n"
            "    const texture = await Assets.load(base + f.file);\n"
            "    texture.source.scaleMode = 'nearest';\n"
            "    return {texture, time: f.duration_ms ?? 1000};\n  }));\n"
            "  const sprite = new AnimatedSprite(frames);\n"
            "  sprite.anchor.set(asset.pivot.x / asset.canvas.width,"
            " asset.pivot.y / asset.canvas.height);\n"
            "  sprite.loop = asset.loop;\n  sprite.animationSpeed = 1;\n"
            "  if (frames.length > 1) sprite.play();\n  return sprite;\n}\n"
        )
    if target == "canvas":
        return "loader.js", (
            f"const asset = {encoded};\n"
            "export async function loadGenSprite(base = '') {\n"
            "  const images = await Promise.all(asset.frames.map(f => new Promise((ok, fail) => {\n"
            "    const image = new Image(); image.onload = () => ok(image);"
            " image.onerror = fail; image.src = base + f.file;\n  })));\n"
            "  return (ctx, x, y, elapsedMs = 0) => {\n"
            "    const total = asset.frames.reduce((sum, f) => sum + (f.duration_ms ?? 1000), 0);\n"
            "    let time = Math.max(0, elapsedMs);\n"
            "    time = asset.loop ? time % total : Math.min(time, total - 0.001);\n"
            "    let i = 0; while (i < images.length - 1 && time >= asset.frames[i].duration_ms)"
            " { time -= asset.frames[i].duration_ms; i++; }\n"
            "    ctx.imageSmoothingEnabled = false;\n"
            "    ctx.drawImage(images[i], x - asset.pivot.x, y - asset.pivot.y);\n  };\n}\n"
        )
    if target == "flame":
        return "loader.dart", (
            "import 'dart:convert';\nimport 'dart:ui' show FilterQuality;\n"
            "import 'package:flame/game.dart';\nimport 'package:flame/components.dart';\n"
            f"final asset = jsonDecode(r'''{encoded}''') as Map<String, dynamic>;\n"
            "Future<SpriteAnimationComponent> loadGenSprite(FlameGame game, String base) async {\n"
            "  final frames = <SpriteAnimationFrame>[];\n"
            "  for (final frame in asset['frames']) {\n"
            "    final image = await game.images.load(base + frame['file']);\n"
            "    frames.add(SpriteAnimationFrame(Sprite(image),"
            " (frame['duration_ms'] ?? 1000) / 1000.0));\n  }\n"
            "  return SpriteAnimationComponent(animation: SpriteAnimation(frames,"
            f" loop: asset['loop']), size: Vector2({width}, {height}),"
            f" anchor: Anchor({px / width}, {py / height}))"
            "..paint.filterQuality = FilterQuality.none;\n}\n"
        )
    unique = asset["asset_id"].replace("_", "")
    durations = ", ".join(str(frame["duration_ms"] or 1000) for frame in frames)
    paths = ", ".join(json.dumps(frame["file"]) for frame in frames)
    if target == "unity":
        name = f"GenSprite{unique}"
        return f"{name}loader.cs", (
            "using System.IO;\nusing UnityEngine;\n"
            f"public static class {name} {{\n"
            f"  public static readonly int[] DurationMs = {{ {durations} }};\n"
            f"  public const bool Loop = {str(asset['loop']).lower()};\n"
            f"  static readonly string[] Frames = {{ {paths} }};\n"
            "  public static Sprite LoadFrame(string packageDirectory, int frame = 0) {\n"
            "    var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);\n"
            "    if (!ImageConversion.LoadImage(texture, File.ReadAllBytes("
            "Path.Combine(packageDirectory, Frames[frame])))) {\n"
            "      Object.Destroy(texture); throw new InvalidDataException(\"Invalid PNG\");\n"
            "    }\n    texture.filterMode = FilterMode.Point;\n"
            "    return Sprite.Create(texture, new Rect(0, 0, texture.width, texture.height),"
            f" new Vector2({px / width}f, {1 - py / height}f), 1f);\n  }}\n}}\n"
        )
    name = f"GenSprite{unique}"
    return f"{name}loader.java", (
        "import com.badlogic.gdx.files.FileHandle;\n"
        "import com.badlogic.gdx.graphics.Texture;\n"
        "import com.badlogic.gdx.graphics.g2d.TextureRegion;\n"
        f"class {name} {{\n"
        f"  static final int[] DURATION_MS = {{ {durations} }};\n"
        f"  static final boolean LOOP = {str(asset['loop']).lower()};\n"
        f"  static final int PIVOT_X = {px}, PIVOT_Y = {py};\n"
        f"  static final String[] FILES = {{ {paths} }};\n"
        "  static TextureRegion[] loadFrames(FileHandle directory) {\n"
        "    TextureRegion[] frames = new TextureRegion[FILES.length];\n"
        "    for (int i = 0; i < FILES.length; i++) {\n"
        "      Texture texture = new Texture(directory.child(FILES[i]));\n"
        "      texture.setFilter(Texture.TextureFilter.Nearest, Texture.TextureFilter.Nearest);\n"
        "      frames[i] = new TextureRegion(texture);\n    }\n    return frames;\n  }\n"
        "  static int frameAt(long elapsedMs) {\n"
        "    long total = 0; for (int ms : DURATION_MS) total += ms;\n"
        "    long time = Math.max(0L, elapsedMs);\n"
        "    time = LOOP ? time % total : Math.min(time, total - 1);\n"
        "    int i = 0; while (i < DURATION_MS.length - 1 && time >= DURATION_MS[i])"
        " { time -= DURATION_MS[i]; i++; }\n    return i;\n  }\n}\n"
    )


def register_export_tools(server: Any, store: AssetStore) -> None:
    exports = ExportStore(store)
    for method in [exports.export_asset, exports.export_godot_character_package,
                   exports.export_godot_tileset_package, exports.detect_engine,
                   exports.integrate_asset, exports.verify_integration]:
        server.tool()(method)
