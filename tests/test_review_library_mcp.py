import asyncio
import base64
import io
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from PIL import Image


def test_real_mcp_reviews_images_and_publishes_named_library(tmp_path):
    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "gensprite_mcp", "--output-dir", str(tmp_path)],
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                names = {tool.name for tool in (await client.list_tools()).tools}
                assert {"review_asset", "build_asset_library"} <= names
                created = await client.call_tool("create_sprite", {
                    "request": {"template": "knight", "description": "Silver Knight"}
                })
                assert not created.isError
                asset = created.structuredContent
                animated = await client.call_tool("generate_animation", {
                    "request": {"asset_id": asset["asset_id"], "motion": "attack"}
                })
                assert not animated.isError
                for identifier in (asset["asset_id"], animated.structuredContent["animation_id"]):
                    reviewed = await client.call_tool("review_asset", {"asset_id": identifier})
                    assert not reviewed.isError, reviewed.content
                    assert isinstance(reviewed.structuredContent, dict)
                    images = [c for c in reviewed.content if isinstance(c, types.ImageContent)]
                    assert len(images) == 1
                    with Image.open(io.BytesIO(base64.b64decode(images[0].data))) as image:
                        assert image.format == "PNG"
                        assert 32 < image.width <= 2048
                        assert 32 < image.height <= 2048
                published = await client.call_tool("build_asset_library", {
                    "asset_ids": [asset["asset_id"]]
                })
                assert not published.isError, published.content
                gallery = Path(published.structuredContent["gallery_path"])
                assert gallery.is_file()
                assert gallery.resolve().is_relative_to(tmp_path.resolve())
                assert "Silver Knight" in gallery.read_text(encoding="utf-8")
                assert Path(asset["png_path"]).is_file()
                invalid = await client.call_tool("build_asset_library", {"asset_ids": []})
                assert invalid.isError

    asyncio.run(exercise())
