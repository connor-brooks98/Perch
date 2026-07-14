#!/usr/bin/env python3
"""Build deterministic raster assets for the canonical Perch mark."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "web/site/icons"
BACKGROUND = "#E9EDE4"
DARK_GREEN = "#2F5139"
CREAM = "#F4F0DF"
AMBER = "#D59A42"
SUPERSAMPLE = 4


def cubic(start, control_a, control_b, end, steps=12):
    """Return sampled points for one cubic Bezier segment."""
    points = []
    for index in range(steps + 1):
        t = index / steps
        inverse = 1 - t
        points.append(
            (
                inverse**3 * start[0]
                + 3 * inverse**2 * t * control_a[0]
                + 3 * inverse * t**2 * control_b[0]
                + t**3 * end[0],
                inverse**3 * start[1]
                + 3 * inverse**2 * t * control_a[1]
                + 3 * inverse * t**2 * control_b[1]
                + t**3 * end[1],
            )
        )
    return points


def bird_outline():
    """Sample the cream bird path from perch-mark.svg."""
    first = cubic((10, 24), (15, 23), (17, 19), (19, 13))
    second = cubic((19, 13), (24, 14), (28, 18), (29, 23))[1:]
    third = cubic((29, 23), (25, 27), (19, 29), (10, 24))[1:]
    return first + second + third


def render(size: int, artwork_fraction: float) -> Image.Image:
    canvas_size = size * SUPERSAMPLE
    image = Image.new("RGB", (canvas_size, canvas_size), BACKGROUND)
    draw = ImageDraw.Draw(image)

    artwork_size = canvas_size * artwork_fraction
    offset = (canvas_size - artwork_size) / 2

    def point(x, y):
        return (offset + x / 40 * artwork_size, offset + y / 40 * artwork_size)

    draw.ellipse((*point(1, 1), *point(39, 39)), fill=DARK_GREEN)
    draw.polygon([point(x, y) for x, y in bird_outline()], fill=CREAM)
    draw.ellipse((*point(20, 14.5), *point(23, 17.5)), fill=DARK_GREEN)
    draw.polygon([point(28, 19), point(34, 21), point(28, 23)], fill=AMBER)

    return image.resize((size, size), Image.Resampling.LANCZOS)


def save_png(name: str, size: int, artwork_fraction: float) -> Image.Image:
    image = render(size, artwork_fraction)
    path = ICONS / name
    image.save(path, format="PNG", optimize=False, compress_level=9)
    print(f"{path.relative_to(ROOT)} {size}x{size}")
    return image


def main():
    ICONS.mkdir(parents=True, exist_ok=True)
    save_png("icon-192.png", 192, 0.90)
    save_png("icon-512.png", 512, 0.90)
    save_png("icon-maskable-512.png", 512, 0.62)
    save_png("apple-touch-icon.png", 180, 0.90)
    favicon = save_png("favicon-32.png", 32, 0.90)
    favicon_path = ROOT / "web/site/favicon.ico"
    favicon.save(favicon_path, format="ICO", sizes=[(16, 16), (32, 32)])
    print(f"{favicon_path.relative_to(ROOT)} 16x16,32x32")


if __name__ == "__main__":
    main()
