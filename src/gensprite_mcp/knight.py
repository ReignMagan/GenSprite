"""Hand-drawn knight poses on an integer 32-cell design grid."""

from PIL import Image, ImageDraw

KNIGHT_PALETTE = [
    "#182337", "#34485F", "#6C8195", "#ABC0CE", "#E6F2F3", "#17365E",
    "#245B98", "#438BC5", "#D8AD57", "#F5D88B", "#812D43", "#C7474F",
    "#F47866", "#684637", "#F8FBEB",
]


def draw_knight(
    width: int, height: int, palette: list[str], motion: str = "idle", frame: int = 0,
) -> Image.Image:
    """Draw a planted, right-facing knight without resizing or filtered pixels."""
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    colors = [palette[min(i, len(palette) - 1)] for i in range(len(KNIGHT_PALETTE))]

    def polygon(points: list[tuple[int, int]], color: int) -> None:
        draw.polygon([(x * width // 32, y * height // 32) for x, y in points],
                     fill=colors[color])

    def rect(box: tuple[int, int, int, int], color: int) -> None:
        x1, y1, x2, y2 = box
        draw.rectangle((x1 * width // 32, y1 * height // 32,
                        (x2 + 1) * width // 32 - 1, (y2 + 1) * height // 32 - 1),
                       fill=colors[color])

    if motion == "idle":
        pose = frame % 4
        bob = (0, -1, 0, 0)[pose]
        plume = (0, 0, 1, -1)[pose]
        hand, tip = (23, 19 + bob), (27, 10 + bob)
    else:
        pose = frame % 6
        bob = (0, 0, -1, 0, 1, 0)[pose]
        plume = (0, -1, -1, 1, 2, 1)[pose]
        hand, tip = [
            ((23, 19), (27, 10)), ((21, 17), (16, 7)),
            ((22, 12), (25, 2)), ((24, 17), (30, 11)),
            ((23, 21), (29, 24)), ((23, 19), (29, 16)),
        ][pose]

    # Greaves and sabatons never move, keeping a stable ground contact in every pose.
    polygon([(11, 23), (16, 23), (16, 27), (17, 28), (17, 29),
             (10, 29), (10, 27)], 0)
    rect((12, 24, 15, 27), 2)
    rect((12, 24, 13, 27), 3)
    rect((11, 28, 15, 28), 3)
    polygon([(18, 23), (22, 23), (22, 27), (24, 28), (24, 29),
             (18, 29), (17, 27)], 0)
    rect((18, 24, 20, 27), 2)
    rect((19, 24, 20, 26), 4)
    rect((19, 28, 23, 28), 3)
    rect((12, 24, 15, 24), 1)
    rect((18, 24, 21, 24), 1)

    # A dark hem separates the blue tabard from the segmented silver armor.
    polygon([(11, 15 + bob), (19, 14 + bob), (22, 18 + bob),
             (21, 22), (22, 25), (17, 26), (16, 24), (11, 25)], 0)
    polygon([(12, 16 + bob), (18, 15 + bob), (20, 18 + bob),
             (20, 22), (21, 24), (18, 24), (16, 22), (12, 24)], 5)
    polygon([(13, 17 + bob), (16, 16 + bob), (16, 22), (13, 23)], 6)
    rect((14, 18 + bob, 14, 22), 7)
    polygon([(11, 14 + bob), (16, 13 + bob), (20, 15 + bob),
             (20, 19 + bob), (17, 21 + bob), (12, 19 + bob)], 1)
    polygon([(12, 15 + bob), (16, 14 + bob), (19, 15 + bob),
             (18, 18 + bob), (15, 19 + bob), (12, 18 + bob)], 3)
    polygon([(13, 15 + bob), (16, 15 + bob), (16, 17 + bob),
             (13, 17 + bob)], 4)
    rect((12, 21, 20, 22), 13)
    rect((16, 21, 17, 22), 8)
    rect((17, 21, 17, 21), 9)

    # The visor projects to the right; its continuous slit stays readable at 32 px.
    polygon([(12, 7 + bob), (15, 5 + bob), (19, 6 + bob), (21, 8 + bob),
             (21, 10 + bob), (23, 11 + bob), (22, 13 + bob),
             (19, 15 + bob), (14, 14 + bob), (12, 12 + bob)], 0)
    polygon([(13, 8 + bob), (16, 6 + bob), (19, 7 + bob), (20, 9 + bob),
             (17, 10 + bob), (13, 10 + bob)], 3)
    rect((15, 7 + bob, 17, 7 + bob), 4)
    rect((13, 9 + bob, 15, 11 + bob), 2)
    polygon([(16, 10 + bob), (20, 10 + bob), (22, 11 + bob),
             (21, 13 + bob), (18, 14 + bob), (15, 12 + bob)], 2)
    rect((16, 10 + bob, 21, 10 + bob), 0)
    rect((18, 11 + bob, 21, 11 + bob), 3)
    rect((19, 12 + bob, 19, 12 + bob), 0)
    rect((21, 12 + bob, 21, 12 + bob), 0)
    rect((15, 12 + bob, 16, 12 + bob), 4)
    rect((16, 13 + bob, 18, 13 + bob), 3)

    polygon([(16, 6 + bob), (15, 3 + bob), (11, 2 + bob),
             (8, 3 + bob + plume), (7, 5 + bob + plume),
             (11, 5 + bob + plume), (13, 7 + bob)], 0)
    polygon([(15, 5 + bob), (14, 3 + bob), (11, 3 + bob),
             (8, 4 + bob + plume), (11, 4 + bob + plume), (13, 6 + bob)], 10)
    polygon([(14, 4 + bob), (11, 3 + bob), (9, 4 + bob + plume),
             (12, 4 + bob + plume), (13, 5 + bob)], 11)
    rect((11, 3 + bob, 12, 3 + bob), 12)
    rect((15, 5 + bob, 16, 5 + bob), 8)

    hx, hy = hand
    tx, ty = tip
    polygon([(19, 15 + bob), (21, 15 + bob), (hx + 1, hy - 1),
             (hx + 1, hy + 1), (hx - 1, hy + 2), (18, 18 + bob)], 0)
    polygon([(20, 16 + bob), (hx, hy), (hx - 1, hy + 1), (19, 18 + bob)], 2)
    rect((19, 15 + bob, 21, 16 + bob), 3)
    rect((19, 15 + bob, 20, 15 + bob), 4)

    # Each blade is a sharp integer polygon; the hilt follows the blade direction.
    dx = (tx > hx) - (tx < hx)
    dy = (ty > hy) - (ty < hy)
    px, py = -dy, dx
    bx, by = hx + 2 * dx, hy + 2 * dy
    polygon([(bx - px, by - py), (tx - dx - px, ty - dy - py),
             (tx, ty), (tx - dx + px, ty - dy + py), (bx + px, by + py)], 0)
    polygon([(bx, by), (tx - dx, ty - dy), (tx, ty),
             (tx - dx + px, ty - dy + py), (bx + px, by + py)], 3)
    polygon([(bx, by), (tx, ty), (tx - dx, ty - dy)], 14)
    polygon([(hx - 2 * px, hy - 2 * py), (hx + 2 * px, hy + 2 * py),
             (hx + 2 * px + dx, hy + 2 * py + dy),
             (hx - 2 * px + dx, hy - 2 * py + dy)], 8)
    rect((hx - 1, hy, hx, hy + 1), 0)
    rect((hx, hy, hx, hy), 3)

    # Foreground shield: bright rim, cobalt face, and a small gold cross.
    polygon([(7, 16 + bob), (11, 15 + bob), (14, 17 + bob),
             (14, 22 + bob), (11, 26 + bob), (7, 23 + bob), (6, 19 + bob)], 0)
    polygon([(8, 17 + bob), (11, 16 + bob), (13, 18 + bob),
             (13, 22 + bob), (11, 24 + bob), (8, 22 + bob), (7, 19 + bob)], 8)
    polygon([(8, 18 + bob), (11, 17 + bob), (12, 18 + bob),
             (12, 22 + bob), (11, 23 + bob), (9, 22 + bob)], 6)
    rect((8, 18 + bob, 8, 20 + bob), 7)
    rect((10, 18 + bob, 10, 21 + bob), 9)
    rect((9, 19 + bob, 11, 19 + bob), 9)
    return image
