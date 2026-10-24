"""Persistent local organization for validated assets; no hosted-account semantics."""

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from pydantic import Field

from .assets import AssetStore
from .models import AnimationManifest

DISCOVERY_LIMIT = 2000
Limit = Annotated[int, Field(strict=True, ge=1, le=200)]


def _identifier(value: str, prefix: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(rf"{prefix}_[0-9a-f]{{32}}", value):
        raise ValueError(f"Invalid {prefix}_ ID; use a generated ID, not a path")
    return value


def _text(value: str, field: str, maximum: int, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.strip()
    if (not value and not empty) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError(f"{field} must contain {'0' if empty else '1'}..{maximum} characters")
    return value


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 200:
        raise ValueError("limit must be an integer from 1 to 200")
    return value


class Catalog:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.store = AssetStore(self.root)
        self.path = self.root / "catalog.sqlite3"
        self._check_paths()
        self.root.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS collections (
                    collection_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    project_id TEXT REFERENCES projects(project_id)
                );
                CREATE TABLE IF NOT EXISTS asset_metadata (
                    asset_id TEXT PRIMARY KEY, label TEXT,
                    project_id TEXT REFERENCES projects(project_id),
                    collection_id TEXT REFERENCES collections(collection_id)
                );
                CREATE TABLE IF NOT EXISTS presets (
                    preset_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    settings TEXT NOT NULL, reference_asset_ids TEXT NOT NULL
                );
            """)

    def _check_paths(self) -> None:
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = Path(str(self.path) + suffix)
            if not path.resolve().is_relative_to(self.root):
                raise ValueError("Catalog path escapes the configured output directory")
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise ValueError("Catalog symlinks are not allowed")

    @contextmanager
    def _connection(self):
        self._check_paths()
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _require(connection, table: str, identifier: str, prefix: str) -> sqlite3.Row:
        _identifier(identifier, prefix)
        field = {"projects": "project_id", "collections": "collection_id"}[table]
        row = connection.execute(
            f"SELECT * FROM {table} WHERE {field} = ?", (identifier,)
        ).fetchone()
        if row is None:
            raise ValueError(f"{field} not found")
        return row

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        """Create a local organization project; q_ IDs differ from palette-profile p_ IDs."""
        project = {
            "project_id": f"q_{uuid4().hex}",
            "name": _text(name, "name", 100),
            "description": _text(description, "description", 2000, empty=True),
        }
        with self._connection() as connection:
            connection.execute("INSERT INTO projects VALUES (?, ?, ?)", tuple(project.values()))
        return project

    def list_projects(self, limit: Limit = 50) -> dict[str, Any]:
        """List persisted projects, newest first, with total and truncation information."""
        limit = _limit(limit)
        with self._connection() as connection:
            total = connection.execute("SELECT count(*) FROM projects").fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return {"projects": [dict(row) for row in rows], "total": total, "truncated": total > limit}

    def create_collection(self, name: str, project_id: str | None = None) -> dict[str, Any]:
        """Create a collection in an optional project; assets inherit its project on assignment."""
        collection = {
            "collection_id": f"c_{uuid4().hex}",
            "name": _text(name, "name", 100),
            "project_id": project_id,
        }
        with self._connection() as connection:
            if project_id is not None:
                self._require(connection, "projects", project_id, "q")
            connection.execute(
                "INSERT INTO collections VALUES (?, ?, ?)", tuple(collection.values())
            )
        return collection

    def list_collections(self, project_id: str | None = None, limit: Limit = 50) -> dict[str, Any]:
        """List persisted collections, optionally filtered by project."""
        limit = _limit(limit)
        clause, values = "", ()
        with self._connection() as connection:
            if project_id is not None:
                self._require(connection, "projects", project_id, "q")
                clause, values = " WHERE project_id = ?", (project_id,)
            total = connection.execute(
                "SELECT count(*) FROM collections" + clause, values
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM collections" + clause + " ORDER BY rowid DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
        return {
            "collections": [dict(row) for row in rows],
            "total": total,
            "truncated": total > limit,
        }

    def _assets(self, asset_ids: list[str]) -> list[str]:
        if not isinstance(asset_ids, list) or not 1 <= len(asset_ids) <= 200:
            raise ValueError("asset_ids must contain 1..200 distinct asset IDs")
        for asset_id in asset_ids:
            _identifier(asset_id, "a")
        if len(set(asset_ids)) != len(asset_ids):
            raise ValueError("asset_ids must be distinct")
        for asset_id in asset_ids:
            report = self.store.validate_sprite(asset_id)
            if report["technical_status"] != "passed":
                raise ValueError(f"Asset {asset_id} failed validation: {report['errors']}")
        return asset_ids

    def assign_assets_to_project(
        self, asset_ids: list[str], project_id: str | None = None
    ) -> dict[str, Any]:
        """Assign sprites atomically; clearing or changing a project clears its collection."""
        asset_ids = self._assets(asset_ids)
        with self._connection() as connection:
            if project_id is not None:
                self._require(connection, "projects", project_id, "q")
            connection.executemany(
                """
                INSERT INTO asset_metadata(asset_id, project_id) VALUES (?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    collection_id = CASE WHEN excluded.project_id IS NOT NULL
                                              AND asset_metadata.project_id IS excluded.project_id
                                         THEN asset_metadata.collection_id ELSE NULL END,
                    project_id = excluded.project_id
            """,
                [(asset_id, project_id) for asset_id in asset_ids],
            )
        return {"asset_ids": asset_ids, "project_id": project_id, "updated": len(asset_ids)}

    def assign_assets_to_collection(
        self, asset_ids: list[str], collection_id: str | None = None
    ) -> dict[str, Any]:
        """Assign sprites atomically and inherit its project; clearing keeps the project."""
        asset_ids = self._assets(asset_ids)
        with self._connection() as connection:
            if collection_id is None:
                connection.executemany(
                    """
                    INSERT INTO asset_metadata(asset_id) VALUES (?)
                    ON CONFLICT(asset_id) DO UPDATE SET collection_id = NULL
                """,
                    [(asset_id,) for asset_id in asset_ids],
                )
            else:
                collection = self._require(connection, "collections", collection_id, "c")
                connection.executemany(
                    """
                    INSERT INTO asset_metadata(asset_id, project_id, collection_id) VALUES (?, ?, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET
                        project_id = excluded.project_id, collection_id = excluded.collection_id
                """,
                    [(asset_id, collection["project_id"], collection_id) for asset_id in asset_ids],
                )
        return {"asset_ids": asset_ids, "collection_id": collection_id, "updated": len(asset_ids)}

    def get_asset_metadata(self, asset_id: str) -> dict[str, Any]:
        """Inspect actual files, validation, immutable ancestry and local organization."""
        _identifier(asset_id, "a")
        info = self.store.inspect_sprite(asset_id)
        png_path = self.store._path("generated", asset_id, "sprite.png")
        manifest_path = self.store._path("generated", asset_id, "manifest.json")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM asset_metadata WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        organization = (
            dict(row) if row else {"label": None, "project_id": None, "collection_id": None}
        )
        manifest = info["manifest"]
        return {
            **manifest,
            **info,
            **organization,
            "palette": manifest["palette"],
            "png_path": str(png_path),
            "manifest_path": str(manifest_path),
            "sprite_url": png_path.as_uri(),
            "manifest_url": manifest_path.as_uri(),
            "status": info["validation"]["status"],
            "parent_asset_id": manifest.get("parent_asset_id"),
            "version_id": asset_id,
        }

    def update_asset_label(self, asset_id: str, label: str | None = None) -> dict[str, Any]:
        """Set a persistent label, or clear it with null; leave the image immutable."""
        self._assets([asset_id])
        if label is not None:
            label = _text(label, "label", 200)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO asset_metadata(asset_id, label) VALUES (?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET label = excluded.label
            """,
                (asset_id, label),
            )
        return {"asset_id": asset_id, "label": label}

    def _discover(self, kind: str, prefix: str) -> tuple[list[tuple[int, str]], bool]:
        directory = self.store._path(kind, f"{prefix}_{'0' * 32}", "manifest.json").parent.parent
        candidates = []
        truncated = False
        try:
            with os.scandir(directory) as entries:
                # shortcut: discovery scans 2,000 entries; add a persisted index for larger stores.
                for index, entry in enumerate(entries):
                    if index == DISCOVERY_LIMIT:
                        truncated = True
                        break
                    if not re.fullmatch(rf"{prefix}_[0-9a-f]{{32}}", entry.name):
                        continue
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    try:
                        path = self.store._path(kind, entry.name, "manifest.json")
                        candidates.append((path.stat().st_mtime_ns, entry.name))
                    except (OSError, ValueError):
                        continue
        except FileNotFoundError:
            return [], False
        except OSError as exc:
            raise ValueError(f"Cannot discover local {kind}: {exc}") from exc
        return sorted(candidates, reverse=True), truncated

    def list_recent_assets(
        self, limit: Limit = 50, project_id: str | None = None, collection_id: str | None = None
    ) -> dict[str, Any]:
        """List validated local sprites, newest first, with bounded discovery and response size."""
        limit = _limit(limit)
        with self._connection() as connection:
            if project_id is not None:
                self._require(connection, "projects", project_id, "q")
            if collection_id is not None:
                self._require(connection, "collections", collection_id, "c")
        candidates, discovery_truncated = self._discover("generated", "a")
        assets, total = [], 0
        for _, asset_id in candidates:
            try:
                info = self.get_asset_metadata(asset_id)
            except (OSError, ValueError):
                continue
            if info["validation"]["technical_status"] != "passed":
                continue
            if project_id is not None and info["project_id"] != project_id:
                continue
            if collection_id is not None and info["collection_id"] != collection_id:
                continue
            total += 1
            if len(assets) < limit:
                assets.append(info)
        return {
            "assets": assets,
            "total": total,
            "total_is_exact": not discovery_truncated,
            "truncated": total > limit or discovery_truncated,
            "discovery_truncated": discovery_truncated,
        }

    def list_animation_outputs(
        self, asset_id: str | None = None, limit: Limit = 50
    ) -> dict[str, Any]:
        """Discover actual validated animation packages, optionally filtered by their source."""
        limit = _limit(limit)
        if asset_id is not None:
            self._assets([asset_id])
        candidates, discovery_truncated = self._discover("animations", "n")
        animations, total = [], 0
        for _, animation_id in candidates:
            try:
                manifest_path = self.store._path("animations", animation_id, "manifest.json")
                manifest = self.store._read(manifest_path, AnimationManifest)
                if manifest.animation_id != animation_id:
                    continue
                if asset_id is not None and manifest.source_asset_id != asset_id:
                    continue
                report = self.store.validate_animation(animation_id)
                if report["technical_status"] != "passed":
                    continue
                spritesheet = self.store._path("animations", animation_id, manifest.spritesheet)
                preview = self.store._path("animations", animation_id, manifest.preview)
                frames = [
                    self.store._path("animations", animation_id, frame.file)
                    for frame in manifest.frames
                ]
                output = {
                    **manifest.model_dump(),
                    "manifest_path": str(manifest_path),
                    "spritesheet_path": str(spritesheet),
                    "preview_path": str(preview),
                    "frame_paths": [str(path) for path in frames],
                    "manifest_url": manifest_path.as_uri(),
                    "spritesheet_url": spritesheet.as_uri(),
                    "preview_url": preview.as_uri(),
                    "validation": report,
                    "status": report["status"],
                }
            except (OSError, ValueError):
                continue
            total += 1
            if len(animations) < limit:
                animations.append(output)
        return {
            "animations": animations,
            "total": total,
            "total_is_exact": not discovery_truncated,
            "truncated": total > limit or discovery_truncated,
            "discovery_truncated": discovery_truncated,
        }

    def save_private_preset(
        self, name: str, settings: dict[str, Any], reference_asset_ids: list[str] | None = None
    ) -> dict[str, Any]:
        """Save bounded JSON settings and optional validated sprite references locally."""
        name = _text(name, "name", 100)
        if not isinstance(settings, dict):
            raise ValueError("settings must be a JSON object")
        try:
            encoded = json.dumps(settings, allow_nan=False, ensure_ascii=False)
            if len(encoded.encode("utf-8")) > 65536:
                raise ValueError("settings exceeds the 64 KiB JSON limit")
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ValueError(f"Invalid preset settings: {exc}") from exc
        references = [] if reference_asset_ids is None else reference_asset_ids
        if not isinstance(references, list):
            raise ValueError("reference_asset_ids must be a list of asset IDs")
        if references:
            self._assets(references)
        preset_id = f"s_{uuid4().hex}"
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO presets VALUES (?, ?, ?, ?)",
                (preset_id, name, encoded, json.dumps(references)),
            )
        return self.get_preset_settings(preset_id)

    def get_preset_settings(self, preset_id: str) -> dict[str, Any]:
        """Return JSON settings ready to pass to the matching generation or animation tool."""
        _identifier(preset_id, "s")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM presets WHERE preset_id = ?", (preset_id,)
            ).fetchone()
        if row is None:
            raise ValueError("preset_id not found")
        return {
            "preset_id": row["preset_id"],
            "name": row["name"],
            "settings": json.loads(row["settings"]),
            "reference_asset_ids": json.loads(row["reference_asset_ids"]),
            "visibility": "private",
        }

    def list_presets(self, limit: Limit = 50) -> dict[str, Any]:
        """List private presets stored locally, newest first."""
        limit = _limit(limit)
        with self._connection() as connection:
            total = connection.execute("SELECT count(*) FROM presets").fetchone()[0]
            rows = connection.execute(
                "SELECT preset_id, name FROM presets ORDER BY rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return {
            "presets": [{**dict(row), "visibility": "private"} for row in rows],
            "total": total,
            "truncated": total > limit,
        }


def register_catalog_tools(server, store: AssetStore) -> None:
    """Register project, collection, metadata and private-preset tools on the MCP server."""
    catalog = Catalog(store.root)
    catalog.store = store
    for name in (
        "create_project",
        "list_projects",
        "create_collection",
        "list_collections",
        "assign_assets_to_project",
        "assign_assets_to_collection",
        "update_asset_label",
        "list_recent_assets",
        "get_asset_metadata",
        "list_animation_outputs",
        "list_presets",
        "get_preset_settings",
        "save_private_preset",
    ):
        server.tool()(getattr(catalog, name))
