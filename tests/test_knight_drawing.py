import re

import pytest
from PIL import ImageColor

from gensprite_mcp.knight import KNIGHT_PALETTE, draw_knight


def test_source_is_deterministic_transparent_native_pixel_art():
    image = draw_knight(32, 32, KNIGHT_PALETTE)
    assert image.mode == "RGBA"
    assert image.size == (32, 32)
    assert image.tobytes() == draw_knight(32, 32, KNIGHT_PALETTE).tobytes()
    assert 1 <= len(KNIGHT_PALETTE) <= 16
    assert all(re.fullmatch(r"#[0-9A-F]{6}", color) for color in KNIGHT_PALETTE)
    assert set(image.getchannel("A").get_flattened_data()) == {0, 255}
    assert image.getbbox()[3] == 30
    colors = {pixel[:3] for pixel in image.get_flattened_data() if pixel[3]}
    assert colors <= {ImageColor.getrgb(color) for color in KNIGHT_PALETTE}
    assert len(colors) >= 10  # The default knight retains armor, heraldry, and plume shading.


@pytest.mark.parametrize("motion,count", [("idle", 4), ("attack", 6)])
@pytest.mark.parametrize("width,height", [(32, 32), (47, 65), (256, 256)])
def test_animation_has_unique_bounded_poses_with_planted_feet(motion, count, width, height):
    frames = [draw_knight(width, height, KNIGHT_PALETTE, motion, i) for i in range(count)]
    assert len({image.tobytes() for image in frames}) == count
    feet = frames[0].crop((0, height * 27 // 32, width, height))
    for image in frames:
        left, top, right, bottom = image.getbbox()
        assert 1 <= left < right <= width - 1
        assert 1 <= top < bottom <= height - 1
        assert image.crop((0, height * 27 // 32, width, height)).tobytes() == feet.tobytes()
        assert set(image.getchannel("A").get_flattened_data()) == {0, 255}
    assert frames[0].tobytes() == draw_knight(
        width, height, KNIGHT_PALETTE, motion, count
    ).tobytes()


@pytest.mark.parametrize("palette", [["#00FF00"], ["#111111", "#EEEEEE"],
                                     [f"#{i:06X}" for i in range(32)]])
def test_custom_palettes_are_locked_even_when_short(palette):
    allowed = {ImageColor.getrgb(color) for color in palette}
    for motion, count in [("idle", 4), ("attack", 6)]:
        for frame in range(count):
            image = draw_knight(32, 32, palette, motion, frame)
            assert image.getbbox() is not None
            assert {p[:3] for p in image.get_flattened_data() if p[3]} <= allowed
