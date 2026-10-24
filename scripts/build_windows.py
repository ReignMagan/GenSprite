"""Build and verify the self-contained local Windows installer."""

import asyncio
import hashlib
import json
import os
import platform
import runpy
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".tools" / "windows-build"


def freeze(name: str, entry: str, options: list[str]) -> Path:
    output = WORK / "dist" / name
    output.mkdir(parents=True, exist_ok=True)
    log = WORK / f"{name}.log"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--noupx",
        "--log-level",
        "WARN",
        "--name",
        name,
        "--paths",
        str(ROOT / "src"),
        "--distpath",
        str(output),
        "--workpath",
        str(WORK / "work" / name),
        "--specpath",
        str(WORK / "specs"),
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "tests",
        *options,
        str(ROOT / entry),
    ]
    print(f"Building {name}...", flush=True)
    with log.open("w", encoding="utf-8") as stream:
        completed = subprocess.run(
            command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=600, check=False
        )
    if completed.returncode:
        print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]))
        raise RuntimeError(f"{name} build failed; see {log}")
    binary = output / f"{name}.exe"
    if not binary.is_file():
        raise RuntimeError(f"{name} build did not produce an executable")
    return binary


def main() -> None:
    if (
        sys.platform != "win32"
        or struct.calcsize("P") != 8
        or platform.machine().lower() != "amd64"
    ):
        raise SystemExit("Build this Windows x64 installer with 64-bit Python on Windows x64.")
    from gensprite_mcp.installer import check_connection

    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "specs").mkdir(exist_ok=True)
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = metadata["project"]["version"]
    server = freeze(
        "GenSpriteMCP",
        "scripts/packaged_server.py",
        [
            "--console",
            "--hide-console",
            "hide-early",
            "--copy-metadata",
            "mcp",
            "--copy-metadata",
            "gensprite-mcp",
            "--collect-data",
            "jsonschema_specifications",
            "--exclude-module",
            "gensprite_mcp.setup_gui",
            "--exclude-module",
            "gensprite_mcp.installer",
            "--exclude-module",
            "tkinter",
        ],
    )
    check_connection([str(server)])
    with tempfile.TemporaryDirectory(prefix="gensprite-exit-check-") as temporary:
        exited = subprocess.run(
            [str(server), "--output-dir", temporary],
            input=b"",
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=30,
        )
        if exited.returncode or b"Traceback" in exited.stderr:
            raise RuntimeError(
                f"Packaged shutdown failed: {exited.stderr.decode(errors='replace')}"
            )
    workflow = runpy.run_path(str(ROOT / "scripts/release_check.py"))
    asyncio.run(asyncio.wait_for(workflow["smoke"]([str(server)]), timeout=120))
    print("Standalone server passed real MCP artwork/animation/validation/export.", flush=True)
    payload = WORK / "payload"
    payload.mkdir(exist_ok=True)
    shutil.copyfile(server, payload / "GenSpriteMCP.exe")
    digest = hashlib.sha256(server.read_bytes()).hexdigest()
    (payload / "manifest.json").write_text(
        json.dumps(
            {
                "version": version,
                "sha256": digest,
                "file": "GenSpriteMCP.exe",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    setup = freeze(
        "GenSprite-Setup",
        "scripts/packaged_setup.py",
        [
            "--windowed",
            "--add-data",
            f"{payload}:payload",
            "--exclude-module",
            "mcp",
            "--exclude-module",
            "PIL",
            "--exclude-module",
            "gensprite_mcp.server",
        ],
    )
    print(
        "Checking packaged GUI installation, backup, repeat setup and separate projects...",
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="gensprite-packaged-check-") as temporary:
        report = Path(temporary) / "report.json"
        environment = dict(os.environ)
        for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
            environment.pop(key, None)
        system = Path(os.environ["SYSTEMROOT"])
        environment["PATH"] = os.pathsep.join((str(system / "System32"), str(system)))
        completed = subprocess.run(
            [str(setup), "--self-check", "--report", str(report)],
            cwd=temporary,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=180,
            check=False,
        )
        details = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
        if completed.returncode or details.get("status") != "passed":
            raise RuntimeError(f"Packaged installer check failed: {details}")
        print(json.dumps(details, indent=2), flush=True)
    release = ROOT / "dist"
    release.mkdir(exist_ok=True)
    # Publish the deliverable only after both packaged workflows have passed.
    artifact = release / "GenSprite-Setup.exe"
    temporary = release / "GenSprite-Setup.exe.tmp"
    shutil.copyfile(setup, temporary)
    os.replace(temporary, artifact)
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (release / "GenSprite-Setup.exe.sha256").write_text(
        f"{checksum}  GenSprite-Setup.exe\n",
        encoding="ascii",
    )
    print(f"Verified local installer: {artifact} ({artifact.stat().st_size / 1048576:.1f} MiB)")


if __name__ == "__main__":
    main()
