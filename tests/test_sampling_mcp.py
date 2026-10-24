import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


def test_real_mcp_client_can_author_pixels_through_sampling(tmp_path):
    requests = []

    async def artist(context, parameters):
        requests.append(parameters)
        rows = ["........"] * 8
        rows[4] = "...XX..."
        return types.CreateMessageResult(
            role="assistant",
            model="regression-authoring-agent",
            content=types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "rows": rows,
                        "palette": {"X": "#00FF00"},
                    }
                ),
            ),
            stopReason="endTurn",
        )

    async def exercise():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "gensprite_mcp", "--output-dir", str(tmp_path)]
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer, sampling_callback=artist) as client:
                await client.initialize()
                result = await client.call_tool(
                    "generate_character",
                    {
                        "prompt": "Two deliberate green pixels",
                        "perspective": "isometric",
                        "width": 8,
                        "height": 8,
                        "wait_seconds": 2,
                    },
                )
                assert not result.isError, result.content
                job = result.structuredContent
                if job["status"] != "completed":
                    result = await client.call_tool(
                        "check_job_status",
                        {
                            "job_id": job["job_id"],
                            "wait_seconds": 2,
                        },
                    )
                    job = result.structuredContent
                assert job["status"] == "completed", job
                asset = job["output"]["assets"][0]
                assert asset["status"] == "ready_for_export"
                resource = await client.read_resource(
                    f"gensprite://assets/{asset['asset_id']}/image"
                )
                assert resource.contents[0].mimeType == "image/png"
                assert len(requests) == 1
                assert requests[0].includeContext == "none"
                assert "Perspective: isometric" in requests[0].messages[0].content.text

    asyncio.run(asyncio.wait_for(exercise(), timeout=30))


def test_malformed_sampling_fence_is_an_actionable_input_error(tmp_path):
    from types import SimpleNamespace

    import pytest

    from gensprite_mcp.assets import AssetStore
    from gensprite_mcp.jobs import JobManager
    from gensprite_mcp.production import Production

    async def invalid_response(**kwargs):
        return SimpleNamespace(content=types.TextContent(type="text", text="```"))

    session = SimpleNamespace(
        client_params=SimpleNamespace(capabilities=SimpleNamespace(sampling=True)),
        create_message=invalid_response,
    )
    context = SimpleNamespace(session=session, request_id="malformed")
    production = Production(AssetStore(tmp_path), JobManager(tmp_path))
    with pytest.raises(ValueError, match="invalid artwork JSON"):
        asyncio.run(production._request(context, "Draw pixels"))
