#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "deploy" / "icons"


MARK_POLYGONS = [
    [
        (161, 94), (159, 93), (155, 93), (154, 94), (140, 94), (139, 95),
        (125, 95), (124, 96), (110, 96), (109, 97), (93, 97), (92, 98),
        (77, 98), (76, 99), (59, 99), (54, 101), (54, 110), (56, 112),
        (62, 112), (63, 113), (63, 127), (74, 127), (74, 112), (75, 111),
        (103, 110), (104, 109), (118, 109), (119, 108), (136, 108),
        (137, 107), (140, 107), (141, 108), (141, 127), (152, 127),
        (152, 108), (154, 106), (160, 106), (161, 105),
    ],
    [
        (134, 59), (129, 61), (126, 64), (124, 68), (124, 75), (130, 82),
        (132, 82), (133, 83), (140, 83), (144, 81), (148, 75), (148, 68),
        (147, 67), (147, 65), (143, 61), (138, 59),
    ],
    [
        (76, 59), (71, 61), (68, 64), (66, 68), (66, 74), (67, 75),
        (67, 77), (72, 82), (74, 83), (82, 83), (88, 79), (90, 75),
        (90, 68), (88, 64), (85, 61), (80, 59),
    ],
]


def transform(points: list[tuple[int, int]], *, size: int) -> list[tuple[float, float]]:
    min_x, min_y, max_x, max_y = 44, 49, 172, 137
    mark_width = max_x - min_x
    mark_height = max_y - min_y

    target_width = size * 0.58
    target_height = size * 0.40
    scale = min(target_width / mark_width, target_height / mark_height)
    actual_width = mark_width * scale
    actual_height = mark_height * scale
    left = (size - actual_width) / 2
    top = (size - actual_height) / 2

    return [
        (left + (x - min_x) * scale, top + (y - min_y) * scale)
        for x, y in points
    ]


def render(size: int = 1024) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    tile_margin = round(size * 0.065)
    radius = round(size * 0.19)
    draw.rounded_rectangle(
        (tile_margin, tile_margin, size - tile_margin, size - tile_margin),
        radius=radius,
        fill=(255, 255, 255, 255),
    )

    for polygon in MARK_POLYGONS:
        draw.polygon(transform(polygon, size=size), fill=(0, 0, 0, 255))

    return image


def main() -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    master = render()

    png_path = ICON_DIR / "workbench-app-icon.png"
    ico_path = ICON_DIR / "workbench-app-icon.ico"
    icns_path = ICON_DIR / "workbench-app-icon.icns"

    master.save(png_path, "PNG")
    master.save(
        ico_path,
        "ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    master.save(icns_path, "ICNS")

    print(png_path)
    print(ico_path)
    print(icns_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
