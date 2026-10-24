"""Run the release tests, lint and an isolated real stdio MCP workflow."""

import asyncio
import base64
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TOOLS = {
    "review_asset",
    "build_asset_library",
    "animate_game_art",
    "assign_assets_to_collection",
    "assign_assets_to_project",
    "auto_slice_asset",
    "cancel_job",
    "cancel_ui_kit",
    "check_character_animation_run",
    "check_job_status",
    "create_asset_upload",
    "create_collection",
    "create_pixel_art",
    "create_project",
    "create_ui_kit",
    "edit_sprite",
    "export_asset",
    "export_godot_character_package",
    "export_godot_tileset_package",
    "extract_ui_kit_components",
    "finalize_asset_upload",
    "finalize_ui_kit",
    "generate_character",
    "generate_character_animations",
    "generate_game_art",
    "generate_tileset",
    "generate_ui_kit_component_sheets",
    "generate_ui_kit_concepts",
    "get_asset_metadata",
    "get_credit_balance",
    "get_preset_settings",
    "get_ui_kit",
    "import_asset",
    "list_active_jobs",
    "list_animation_outputs",
    "list_character_workflows",
    "list_collections",
    "list_generation_models",
    "list_presets",
    "list_projects",
    "list_recent_assets",
    "list_tileset_options",
    "list_ui_kits",
    "remove_background",
    "report_integration_error",
    "save_private_preset",
    "select_ui_kit_concept",
    "set_asset_alpha_cutoff",
    "update_asset_label",
    "validate_animation",
    "validate_sprite",
}


async def smoke(command: list[str] | None = None) -> None:
    """Verify real tool discovery, native artwork, animation, validation and ZIP output."""
    with tempfile.TemporaryDirectory(prefix="gensprite-release-") as temporary:
        root = Path(temporary).resolve()
        invocation = command or [sys.executable, "-m", "gensprite_mcp"]
        parameters = StdioServerParameters(
            command=invocation[0],
            args=[*invocation[1:], "--output-dir", str(root)],
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                initialized = await client.initialize()
                assert initialized.serverInfo.name == "GenSprite"
                tools = {tool.name for tool in (await client.list_tools()).tools}
                assert REQUIRED_TOOLS <= tools, f"Missing tools: {sorted(REQUIRED_TOOLS - tools)}"

                async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                    result = await client.call_tool(name, arguments)
                    assert not result.isError, f"{name} failed: {result.content}"
                    assert isinstance(result.structuredContent, dict), f"{name} returned no object"
                    return result.structuredContent

                frames = []
                for row in ("..XX....", "...XX..."):
                    frame = await call(
                        "create_pixel_art",
                        {
                            "rows": ["........"] * 4 + [row] + ["........"] * 3,
                            "palette": {"X": "#00FF00"},
                            "description": "Temporary release-check pose",
                        },
                    )
                    assert frame["status"] == "ready_for_export"
                    path = Path(frame["png_path"])
                    assert path.is_file() and path.resolve().is_relative_to(root)
                    validated = await call("validate_sprite", {"asset_id": frame["asset_id"]})
                    assert validated["technical_status"] == "passed" and not validated["errors"]
                    frames.append(frame["asset_id"])
                submitted = await call(
                    "animate_game_art",
                    {
                        "asset_id": frames[0],
                        "prompt": "walk",
                        "frame_asset_ids": frames,
                        "durations_ms": [80, 120],
                        "loop": True,
                    },
                )
                job = await call(
                    "check_job_status",
                    {
                        "job_id": submitted["job_id"],
                        "wait_seconds": 10,
                    },
                )
                assert job["status"] == "completed", f"Animation job failed or timed out: {job}"
                animation = job["output"]
                assert animation["frame_count"] == 2
                assert animation["status"] == "ready_for_export"
                validated = await call(
                    "validate_animation",
                    {
                        "animation_id": animation["animation_id"],
                    },
                )
                assert validated["technical_status"] == "passed" and not validated["errors"]
                exported = await call(
                    "export_asset",
                    {
                        "asset_id": animation["animation_id"],
                        "target": "generic",
                    },
                )
                assert exported["status"] == "ready_for_export"
                archive = Path(exported["zip_path"])
                assert archive.is_file() and archive.resolve().is_relative_to(root)
                with zipfile.ZipFile(archive) as package:
                    assert package.testzip() is None
                    contract = json.loads(package.read("import.json"))
                    assert contract["primary_asset_id"] == animation["animation_id"]
                    record = next(
                        item
                        for item in contract["assets"]
                        if item["asset_id"] == animation["animation_id"]
                    )
                    assert [frame["duration_ms"] for frame in record["frames"]] == [80, 120]
                    assert len([name for name in package.namelist() if name.endswith(".png")]) >= 3
                for identifier in (frames[0], animation["animation_id"]):
                    reviewed = await client.call_tool("review_asset", {"asset_id": identifier})
                    assert not reviewed.isError, reviewed.content
                    images = [item for item in reviewed.content if item.type == "image"]
                    assert len(images) == 1 and images[0].mimeType == "image/png"
                    assert base64.b64decode(images[0].data).startswith(b"\x89PNG\r\n\x1a\n")
                    assert isinstance(reviewed.structuredContent, dict)
                library = await call("build_asset_library", {"asset_ids": [frames[0]]})
                gallery = Path(library["gallery_path"])
                assert gallery.is_file() and gallery.resolve().is_relative_to(root)
                assert "Temporary release-check pose" in gallery.read_text(encoding="utf-8")
                assert Path(library["index_path"]).is_file()
    assert not root.exists(), "Release-check temporary assets were not removed"


def main() -> None:
    for arguments in (["pytest", "-W", "error"], ["ruff", "check", "."]):
        print(f"Running {sys.executable} -m {' '.join(arguments)}", flush=True)
        subprocess.run([sys.executable, "-m", *arguments], cwd=ROOT, check=True, timeout=300)
    print("Running isolated stdio MCP release smoke", flush=True)
    asyncio.run(asyncio.wait_for(smoke(), timeout=90))
    print("Release checks passed: tests, lint, MCP artwork/animation/export/review/library.")


if __name__ == "__main__":
    main()
