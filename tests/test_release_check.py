import asyncio
import runpy
import sys
from pathlib import Path


def test_release_workflow_accepts_an_explicit_server_command():
    release = runpy.run_path(str(Path(__file__).parents[1] / "scripts/release_check.py"))
    asyncio.run(release["smoke"]([sys.executable, "-m", "gensprite_mcp"]))
