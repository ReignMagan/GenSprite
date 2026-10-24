import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_real_stdio_tools_and_persisted_assets(tmp_path):
    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "gensprite_mcp", "--output-dir", str(tmp_path)],
            env=dict(os.environ),
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                initialized = await client.initialize()
                assert initialized.serverInfo.name == "GenSprite"
                tools = await client.list_tools()
                assert {
                    "create_project_profile",
                    "get_project_profile",
                    "create_sprite",
                    "inspect_sprite",
                    "validate_sprite",
                    "generate_animation",
                    "validate_animation",
                } <= {tool.name for tool in tools.tools}
                profile = await client.call_tool(
                    "create_project_profile",
                    {
                        "profile": {"name": "Test icons", "palette": ["#FF0000"]},
                    },
                )
                assert not profile.isError
                profile_id = profile.structuredContent["profile_id"]
                loaded = await client.call_tool("get_project_profile", {"profile_id": profile_id})
                assert loaded.structuredContent["name"] == "Test icons"
                created = await client.call_tool(
                    "create_sprite",
                    {
                        "request": {
                            "template": "heart",
                            "width": 32,
                            "height": 32,
                            "profile_id": profile_id,
                            "description": "Transparent heart",
                        },
                    },
                )
                assert not created.isError
                data = created.structuredContent
                assert data["status"] == "ready_for_export"
                assert Path(data["png_path"]).is_file()
                asset_id = data["asset_id"]
                inspected = await client.call_tool("inspect_sprite", {"asset_id": asset_id})
                assert inspected.structuredContent["colors"] == ["#FF0000"]
                validated = await client.call_tool("validate_sprite", {"asset_id": asset_id})
                assert validated.structuredContent["technical_status"] == "passed"
                bad = await client.call_tool("create_sprite", {"request": {"template": "wizard"}})
                assert bad.isError
                bad = await client.call_tool("inspect_sprite", {"asset_id": "../secret"})
                assert bad.isError
                bad = await client.call_tool("create_sprite", {"request": {"width": 999999}})
                assert bad.isError
                good = await client.call_tool("validate_sprite", {"asset_id": asset_id})
                assert not good.isError
                knight = await client.call_tool(
                    "create_sprite",
                    {
                        "request": {"template": "knight", "description": "Silver knight"},
                    },
                )
                assert not knight.isError
                knight_id = knight.structuredContent["asset_id"]
                for motion, count in [("idle", 4), ("attack", 6)]:
                    animation = await client.call_tool(
                        "generate_animation",
                        {
                            "request": {"asset_id": knight_id, "motion": motion},
                        },
                    )
                    assert not animation.isError, animation.content
                    assert animation.structuredContent["frame_count"] == count
                    animation_id = animation.structuredContent["animation_id"]
                    report = await client.call_tool(
                        "validate_animation",
                        {
                            "animation_id": animation_id,
                        },
                    )
                    assert not report.isError
                    assert report.structuredContent["technical_status"] == "passed"
                    assert report.structuredContent["status"] == "ready_for_export"
                bad = await client.call_tool(
                    "generate_animation",
                    {
                        "request": {"asset_id": knight_id, "motion": "teleport"},
                    },
                )
                assert bad.isError
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                loaded = await client.call_tool("inspect_sprite", {"asset_id": asset_id})
                assert loaded.structuredContent["width"] == 32
                persisted = await client.call_tool(
                    "validate_animation",
                    {
                        "animation_id": animation_id,
                    },
                )
                assert persisted.structuredContent["technical_status"] == "passed"

    asyncio.run(asyncio.wait_for(exercise(), timeout=45))


def test_stdio_shutdown_preserves_the_callers_standard_streams(tmp_path):
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from gensprite_mcp.server import main;main();print('streams-preserved')",
            "--output-dir",
            str(tmp_path),
        ],
        input=b"",
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"streams-preserved"
    assert b"Traceback" not in result.stderr
