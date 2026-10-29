"""Local Windows setup: verified runtime, safe client configuration, real MCP check."""

import ctypes
import hashlib
import json
import os
import queue
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import tomlkit

MAX_CONFIG = 1024 * 1024
MAX_RESPONSE = 256 * 1024
REQUIRED_TOOLS = {"generate_game_art", "animate_game_art", "import_asset", "export_asset"}


@dataclass(frozen=True)
class InstallResult:
    executable: Path
    config_path: Path
    output_dir: Path
    backup_path: Path | None
    tool_count: int


def _safe(path: Path) -> None:
    for part in (path, *path.parents):
        try:
            attributes = getattr(part.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            attributes = 0
        if part.is_symlink() or attributes & 0x400:
            raise ValueError(f"Setup cannot write through a link or reparse point: {part}")


def _check_output(path: Path) -> None:
    _safe(path)
    if path.exists() and not path.is_dir():
        raise ValueError(
            "The project's .gensprite path must be a directory; move the existing file and retry"
        )


def _read_config(path: Path) -> bytes | None:
    _safe(path)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_CONFIG:
        raise ValueError("Client configuration must be a file no larger than 1 MiB")
    with path.open("rb") as stream:
        raw = stream.read(MAX_CONFIG + 1)
    if len(raw) > MAX_CONFIG:
        raise ValueError("Client configuration exceeds 1 MiB")
    return raw


def prepare_config(existing: bytes | None, executable: Path, project: Path) -> bytes:
    if existing is not None and len(existing) > MAX_CONFIG:
        raise ValueError("Codex configuration exceeds 1 MiB")
    try:
        document = tomlkit.parse((existing or b"").decode("utf-8-sig"))
        servers = document.setdefault("mcp_servers", tomlkit.table())
        if not isinstance(servers, Mapping):
            raise ValueError("mcp_servers must be a table")
        server = servers.setdefault("gensprite", tomlkit.table())
        if not isinstance(server, Mapping):
            raise ValueError("gensprite must be a table")
        for key in (
            "url",
            "bearer_token_env_var",
            "http_headers",
            "env_http_headers",
            "oauth",
            "experimental_environment",
        ):
            server.pop(key, None)
        server["command"] = str(executable)
        server["args"] = ["--output-dir", str(project / ".gensprite")]
        server["cwd"] = str(project)
        server["enabled"] = True
        server["startup_timeout_sec"] = 60
        updated = tomlkit.dumps(document).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, KeyError) as exc:
        raise ValueError("Codex configuration is invalid; correct it before connecting") from exc
    if len(updated) > MAX_CONFIG:
        raise ValueError("Updated Codex configuration exceeds 1 MiB")
    return updated


def prepare_opencode_config(existing: bytes | None, executable: Path, project: Path) -> bytes:
    """Preserve strict JSON settings and the existing OpenCode v1/v2 layout."""
    if existing is not None and len(existing) > MAX_CONFIG:
        raise ValueError("OpenCode configuration exceeds 1 MiB")

    def unique_object(pairs):
        document = {}
        for key, value in pairs:
            if key in document:
                raise ValueError("Duplicate JSON key")
            document[key] = value
        return document

    try:
        document = json.loads(
            (existing or b"{}").decode("utf-8-sig"), object_pairs_hook=unique_object,
        )
        if not isinstance(document, dict):
            raise ValueError("Configuration must be an object")
        servers = document.setdefault("mcp", {})
        if not isinstance(servers, dict):
            raise ValueError("mcp must be an object")
        named_server = servers.get("servers")
        v2 = "servers" in servers and not (
            isinstance(named_server, dict) and (
                named_server.get("type") in ("local", "remote")
                or isinstance(named_server.get("enabled"), bool)
            )
        )
        if v2:
            servers = servers["servers"]
            if not isinstance(servers, dict):
                raise ValueError("mcp.servers must be an object")
        previous = servers.get("gensprite", {})
        if not isinstance(previous, dict):
            raise ValueError("gensprite must be an object")
        # Keep client policy outside the server entry; replace obsolete transport settings.
        server = {
            "type": "local",
            "command": [str(executable), "--output-dir", str(project / ".gensprite")],
        }
        for key in ("environment", "codemode", "protocol"):
            if key in previous:
                server[key] = previous[key]
        if v2:
            timeout = previous.get("timeout", {})
            if not isinstance(timeout, dict):
                raise ValueError("v2 timeout must be an object")
            server.update(disabled=False, timeout={**timeout, "startup": 60000})
        else:
            server.update(enabled=True, timeout=60000)
        servers["gensprite"] = server
        document.setdefault("$schema", "https://opencode.ai/config.json")
        updated = (
            json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode()
    except (ValueError, TypeError, UnicodeError, KeyError) as exc:
        raise ValueError(
            "OpenCode configuration requires valid JSON. JSONC comments/trailing commas are "
            "preserved by refusing automatic edits; add the local GenSprite entry manually "
            "using docs/deployment.md. Existing configuration was not changed."
        ) from exc
    if len(updated) > MAX_CONFIG:
        raise ValueError("Updated OpenCode configuration exceeds 1 MiB")
    return updated


def _stop(process: subprocess.Popen) -> None:
    if process.stdin:
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
                check=False,
            )
        else:
            process.kill()
        process.wait(timeout=10)


def check_connection(command: list[str], timeout: float = 60) -> dict:
    """Initialize the real server and discover tools using an isolated temporary store."""
    if not command or not 0 < timeout <= 120:
        raise ValueError("A server command and timeout from 0 to 120 seconds are required")
    with tempfile.TemporaryDirectory(prefix="gensprite-connection-") as temporary:
        environment = dict(os.environ)
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        frozen_windows = os.name == "nt" and getattr(sys, "frozen", False)
        if frozen_windows:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            process = subprocess.Popen(
                [*command, "--output-dir", temporary],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError as exc:
            raise ValueError(f"Could not start GenSprite: {exc}") from exc
        finally:
            if frozen_windows:
                ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))
        received: queue.Queue = queue.Queue(maxsize=8)

        def reader() -> None:
            while True:
                line = process.stdout.readline(MAX_RESPONSE + 1)
                try:
                    received.put_nowait(line)
                except queue.Full:
                    return
                if not line or len(line) > MAX_RESPONSE:
                    return

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        deadline = time.monotonic() + timeout

        def send(message: dict) -> None:
            process.stdin.write(json.dumps(message).encode() + b"\n")
            process.stdin.flush()

        def response(identifier: int) -> dict:
            while True:
                try:
                    line = received.get(timeout=max(0.001, deadline - time.monotonic()))
                except queue.Empty as exc:
                    raise ValueError(
                        "GenSprite connection check timed out; close the MCP client and retry"
                    ) from exc
                if not line:
                    raise ValueError("GenSprite closed before responding; reinstall and retry")
                if len(line) > MAX_RESPONSE:
                    raise ValueError("GenSprite response exceeds the connection-check limit")
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    raise ValueError("GenSprite returned an invalid JSON response") from exc
                if not isinstance(message, dict):
                    raise ValueError("GenSprite returned an invalid response")
                if message.get("id") == identifier:
                    if "error" in message or not isinstance(message.get("result"), dict):
                        raise ValueError("GenSprite rejected the connection check")
                    return message["result"]
                if time.monotonic() >= deadline:
                    raise ValueError("GenSprite connection check timed out")

        try:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "GenSprite Setup", "version": "1"},
                    },
                }
            )
            initialized = response(1)
            if initialized.get("serverInfo", {}).get("name") != "GenSprite":
                raise ValueError("The installed program is not the GenSprite MCP")
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            tools = response(2).get("tools")
            if not isinstance(tools, list) or not REQUIRED_TOOLS <= {
                tool.get("name") for tool in tools if isinstance(tool, dict)
            }:
                raise ValueError(
                    "GenSprite is missing required production tools; reinstall and retry"
                )
            return {"server_name": "GenSprite", "tool_count": len(tools)}
        except (OSError, BrokenPipeError) as exc:
            raise ValueError(
                "GenSprite closed during the connection check; reinstall and retry"
            ) from exc
        finally:
            _stop(process)
            thread.join(timeout=2)
            if process.stdout:
                process.stdout.close()


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _replace_config(temporary: Path, target: Path, existed: bool) -> None:
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        if existed:
            replace = kernel.ReplaceFileW
            replace.argtypes = [wintypes.LPCWSTR] * 3 + [
                wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            replace.restype = wintypes.BOOL
            # ReplaceFile preserves the existing configuration's ACL and file metadata.
            succeeded = replace(str(target), str(temporary), None, 0, None, None)
        else:
            move = kernel.MoveFileExW
            move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
            move.restype = wintypes.BOOL
            succeeded = move(str(temporary), str(target), 8)
        if not succeeded:
            raise ctypes.WinError(ctypes.get_last_error())
    elif existed:
        os.replace(temporary, target)
    else:
        os.link(temporary, target)
        temporary.unlink()


def connect_project(
    project: Path,
    source: Path,
    expected_sha256: str,
    version: str,
    install_root: Path,
    progress: Callable[[str], None] | None = None,
    *, client: str = "codex",
) -> InstallResult:
    if client not in ("codex", "opencode"):
        raise ValueError("client must be codex or opencode")
    project, source, install_root = project.absolute(), source.absolute(), install_root.absolute()
    for path in (project, source, install_root):
        _safe(path)
    if not project.is_dir() or project == Path(project.anchor):
        raise ValueError("Choose an existing game project folder")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid installer version")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Invalid runtime digest")
    if not source.is_file() or source.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("GenSprite runtime is missing or too large; download setup again")
    if _digest(source) != expected_sha256:
        raise ValueError("GenSprite runtime digest changed; download setup again")
    config = project / ".codex" / "config.toml"
    if client == "opencode":
        config = project / "opencode.json"
        commented = project / "opencode.jsonc"
        _safe(commented)
        if commented.exists():
            if config.exists():
                raise ValueError("Both OpenCode JSON and JSONC configurations exist; edit manually")
            config = commented
    output = project / ".gensprite"
    _check_output(output)
    original = _read_config(config)
    executable = (
        install_root / "versions" / f"{version}-{expected_sha256[:12]}" / "GenSpriteMCP.exe"
    )
    prepare = prepare_config if client == "codex" else prepare_opencode_config
    updated = prepare(original, executable, project)
    if progress:
        progress("Installing GenSprite...")
    _safe(executable)
    executable.parent.mkdir(parents=True, exist_ok=True)
    if not executable.exists() or _digest(executable) != expected_sha256:
        temporary = executable.with_name(f"{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as target, source.open("rb") as payload:
                shutil.copyfileobj(payload, target)
            if _digest(temporary) != expected_sha256:
                raise ValueError("Runtime changed while copying; download setup again")
            _safe(executable)
            os.replace(temporary, executable)
        finally:
            temporary.unlink(missing_ok=True)
    if progress:
        progress("Checking the MCP connection...")
    checked = check_connection([str(executable)])
    if progress:
        progress(f"Saving your {'Codex' if client == 'codex' else 'OpenCode'} connection...")
    _safe(config)
    _check_output(output)
    if _read_config(config) != original:
        raise ValueError("Client configuration changed during setup; close its editor and retry")
    backup = None
    if updated != original:
        if original is not None:
            identity = hashlib.sha256(str(project).encode()).hexdigest()[:16]
            backup = install_root / "backups" / identity / f"config-{uuid4().hex}{config.suffix}"
            _safe(backup)
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with backup.open("xb") as previous:
                previous.write(original)
        config.parent.mkdir(exist_ok=True)
        _safe(config)
        temporary = config.with_name(f"gensprite-{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as target:
                target.write(updated)
                target.flush()
                os.fsync(target.fileno())
            if original is not None:
                os.chmod(temporary, stat.S_IMODE(config.stat().st_mode))
            if _read_config(config) != original:
                raise ValueError("Client configuration changed during setup; retry")
            _replace_config(temporary, config, original is not None)
        finally:
            temporary.unlink(missing_ok=True)
    return InstallResult(executable, config, output, backup, checked["tool_count"])
