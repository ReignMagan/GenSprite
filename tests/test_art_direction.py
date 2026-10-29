import pytest


def test_brief_carries_requested_canvas_palette_and_animation_identity():
    from gensprite_mcp.art_direction import sprite_art_brief

    brief = sprite_art_brief(
        "A forest ranger with a crossbow", width=32, height=48,
        palette=["#112233", "#AABBCC"],
    )
    assert brief["canvas"] == {"width": 32, "height": 48}
    assert brief["palette"] == ["#112233", "#AABBCC"]
    assert "forest ranger" in brief["image_prompt"]
    assert "32x48" in brief["image_prompt"]
    assert "#112233" in brief["image_prompt"]
    assert "pivot" in brief["animation_guidance"]
    assert any("prepare_sprite" in step for step in brief["workflow"])


@pytest.mark.parametrize("kwargs", [
    {"description": ""}, {"description": "x", "width": True},
    {"description": "x", "perspective": "unknown"},
    {"description": "x", "palette": ["bad"]},
])
def test_brief_rejects_invalid_art_contract(kwargs):
    from gensprite_mcp.art_direction import sprite_art_brief

    with pytest.raises(ValueError):
        sprite_art_brief(**kwargs)
