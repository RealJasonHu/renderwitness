#!/usr/bin/env python3
"""Generate deterministic before/after screenshots for the RenderWitness demo.

The images intentionally contain three kinds of change:

* a harmless card-shadow adjustment;
* a clipped Chinese call-to-action label; and
* a missing refresh glyph whose button still occupies layout space.

No browser, network access, or bundled font is required.  A fixed font search order
keeps output stable on a given machine while still supporting macOS, Linux, and
Windows developer environments.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError as exc:  # pragma: no cover - actionable when run outside dev deps
    raise SystemExit("Pillow is required: python -m pip install Pillow") from exc


WIDTH = 1440
HEIGHT = 900
SCALE = 2

INK = "#172033"
MUTED = "#6B7280"
PURPLE = "#6D5CE7"
PURPLE_DARK = "#4C3FC3"
PURPLE_PALE = "#EEEBFF"
TEAL = "#16A394"
RED = "#E65364"
AMBER = "#E6A23C"
LINE = "#E7E9F1"
SURFACE = "#FFFFFF"


FONT_CANDIDATES: tuple[Path, ...] = (
    # macOS CJK fonts, in stable preference order.
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    # Common Linux images and CI runners.
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    # Windows fallback when the repository is cloned there.
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/arialuni.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)


def _font_path() -> Path | None:
    return next((path for path in FONT_CANDIDATES if path.is_file()), None)


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _font_path()
    if path is None:
        return ImageFont.load_default()
    return ImageFont.truetype(str(path), size * SCALE)


def xy(values: Iterable[float]) -> tuple[int, ...]:
    return tuple(round(value * SCALE) for value in values)


def rounded_rectangle(
    canvas: Image.Image,
    box: Sequence[float],
    *,
    radius: float,
    fill: str,
    outline: str | None = None,
    width: int = 1,
) -> None:
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        xy(box),
        radius=round(radius * SCALE),
        fill=fill,
        outline=outline,
        width=width * SCALE,
    )


def card(
    canvas: Image.Image,
    box: Sequence[float],
    *,
    candidate: bool,
    radius: int = 18,
) -> None:
    """Draw a card with the demo's intentional, cosmetic shadow change."""
    x1, y1, x2, y2 = box
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    # The candidate deliberately changes only these shadow values.
    y_offset = 8 if candidate else 5
    alpha = 16 if candidate else 24
    blur = 15 if candidate else 11
    shadow_draw.rounded_rectangle(
        xy((x1, y1 + y_offset, x2, y2 + y_offset)),
        radius=radius * SCALE,
        fill=(35, 40, 70, alpha),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur * SCALE))
    canvas.alpha_composite(shadow)
    rounded_rectangle(canvas, box, radius=radius, fill=SURFACE, outline="#EEF0F5")


def text(
    canvas: Image.Image,
    position: tuple[float, float],
    value: str,
    *,
    size: int,
    fill: str = INK,
    anchor: str = "la",
) -> None:
    ImageDraw.Draw(canvas).text(xy(position), value, font=font(size), fill=fill, anchor=anchor)


def line(
    canvas: Image.Image,
    points: Sequence[tuple[float, float]],
    *,
    fill: str,
    width: int = 2,
    joint: str = "curve",
) -> None:
    ImageDraw.Draw(canvas).line(
        [xy(point) for point in points], fill=fill, width=width * SCALE, joint=joint
    )


def circle(
    canvas: Image.Image,
    center: tuple[float, float],
    radius: float,
    *,
    fill: str,
    outline: str | None = None,
    width: int = 1,
) -> None:
    x, y = center
    ImageDraw.Draw(canvas).ellipse(
        xy((x - radius, y - radius, x + radius, y + radius)),
        fill=fill,
        outline=outline,
        width=width * SCALE,
    )


def shield(canvas: Image.Image, center: tuple[float, float], color: str) -> None:
    x, y = center
    draw = ImageDraw.Draw(canvas)
    draw.polygon(
        [
            xy((x, y - 13)),
            xy((x + 12, y - 8)),
            xy((x + 9, y + 8)),
            xy((x, y + 15)),
            xy((x - 9, y + 8)),
            xy((x - 12, y - 8)),
        ],
        fill=color,
    )
    line(canvas, [(x - 5, y), (x - 1, y + 4), (x + 6, y - 4)], fill="#FFFFFF", width=2)


def refresh_icon(canvas: Image.Image, center: tuple[float, float], color: str) -> None:
    x, y = center
    draw = ImageDraw.Draw(canvas)
    draw.arc(xy((x - 8, y - 8, x + 8, y + 8)), 35, 300, fill=color, width=2 * SCALE)
    draw.polygon(
        [xy((x + 7, y - 8)), xy((x + 10, y - 2)), xy((x + 3, y - 3))],
        fill=color,
    )


def chevron(canvas: Image.Image, center: tuple[float, float], color: str) -> None:
    x, y = center
    line(canvas, [(x - 3, y - 5), (x + 2, y), (x - 3, y + 5)], fill=color, width=2)


def sidebar_icon(canvas: Image.Image, kind: str, center: tuple[float, float], color: str) -> None:
    x, y = center
    draw = ImageDraw.Draw(canvas)
    if kind == "overview":
        for dx, dy in ((-7, -7), (3, -7), (-7, 3), (3, 3)):
            draw.rounded_rectangle(
                xy((x + dx, y + dy, x + dx + 7, y + dy + 7)), radius=2 * SCALE, fill=color
            )
    elif kind == "compare":
        line(canvas, [(x - 8, y - 5), (x + 8, y - 5)], fill=color, width=2)
        line(canvas, [(x - 8, y + 5), (x + 8, y + 5)], fill=color, width=2)
        circle(canvas, (x - 2, y - 5), 3, fill=color)
        circle(canvas, (x + 4, y + 5), 3, fill=color)
    elif kind == "scenarios":
        draw.rounded_rectangle(
            xy((x - 8, y - 9, x + 8, y + 9)), radius=3 * SCALE, outline=color, width=2 * SCALE
        )
        line(canvas, [(x - 4, y - 3), (x + 4, y - 3)], fill=color, width=2)
        line(canvas, [(x - 4, y + 3), (x + 2, y + 3)], fill=color, width=2)
    else:
        draw.regular_polygon((xy((x, y)), 9 * SCALE), n_sides=6, fill=None, outline=color)
        circle(canvas, (x, y), 3, fill=color)


def draw_sidebar(canvas: Image.Image) -> None:
    draw = ImageDraw.Draw(canvas)
    for y in range(HEIGHT * SCALE):
        ratio = y / (HEIGHT * SCALE - 1)
        color = (
            round(28 + 9 * ratio),
            round(28 + 3 * ratio),
            round(55 + 20 * ratio),
            255,
        )
        draw.line([(0, y), (244 * SCALE, y)], fill=color)

    shield(canvas, (32, 38), PURPLE)
    text(canvas, (53, 38), "RenderWitness", size=19, fill="#FFFFFF", anchor="lm")
    text(canvas, (24, 92), "工作区", size=11, fill="#8F92AE")

    nav = (
        ("overview", "质量总览"),
        ("compare", "视觉对比"),
        ("scenarios", "测试场景"),
        ("settings", "项目设置"),
    )
    for index, (kind, label) in enumerate(nav):
        y = 132 + index * 54
        selected = index == 0
        if selected:
            rounded_rectangle(canvas, (16, y - 20, 228, y + 20), radius=10, fill="#3A365E")
            rounded_rectangle(canvas, (16, y - 11, 19, y + 11), radius=2, fill="#8D7DFF")
        color = "#FFFFFF" if selected else "#AEB1C6"
        sidebar_icon(canvas, kind, (38, y), color)
        text(canvas, (61, y), label, size=14, fill=color, anchor="lm")

    rounded_rectangle(canvas, (18, 750, 226, 828), radius=14, fill="#2E2C4B", outline="#454160")
    circle(canvas, (43, 780), 12, fill="#42C7B8")
    text(canvas, (43, 780), "✓", size=12, fill="#122A2A", anchor="mm")
    text(canvas, (64, 775), "本地模型已连接", size=13, fill="#FFFFFF", anchor="lm")
    text(canvas, (64, 797), "qwen2.5-vl · 7B", size=11, fill="#9699AE", anchor="lm")
    text(canvas, (24, 864), "v0.1.0 · rootless", size=11, fill="#777B97")


def draw_topbar(canvas: Image.Image, *, candidate: bool) -> None:
    text(canvas, (284, 37), "发布质量总览", size=26, fill=INK, anchor="lm")
    text(canvas, (284, 67), "shop-web  /  Pull Request #42", size=13, fill=MUTED, anchor="lm")

    rounded_rectangle(canvas, (1030, 25, 1190, 67), radius=12, fill="#F0F1F6")
    circle(canvas, (1053, 46), 5, fill=TEAL)
    text(canvas, (1067, 46), "main  →  pr-42", size=12, fill="#41485A", anchor="lm")

    rounded_rectangle(canvas, (1204, 25, 1246, 67), radius=12, fill=SURFACE, outline=LINE)
    # Intentional regression: the candidate retains the hit target and layout space,
    # but loses its visible refresh affordance.
    if not candidate:
        refresh_icon(canvas, (1225, 46), "#51586B")

    rounded_rectangle(canvas, (1260, 25, 1400, 67), radius=12, fill=PURPLE)
    text(canvas, (1330, 46), "重新运行", size=13, fill="#FFFFFF", anchor="mm")
    line(canvas, [(244, 91), (1440, 91)], fill="#E9EAF0", width=1)


def sparkline(canvas: Image.Image, points: Sequence[tuple[float, float]], color: str) -> None:
    line(canvas, points, fill=color, width=3)
    last = points[-1]
    circle(canvas, last, 4, fill=SURFACE, outline=color, width=2)


def draw_metrics(canvas: Image.Image, *, candidate: bool) -> None:
    cards = (
        (284, 118, 541, 246, "已检查场景", "128", "+12", TEAL),
        (559, 118, 816, 246, "语义回归", "3", "需处理", RED),
        (834, 118, 1091, 246, "无害变化", "17", "已忽略", PURPLE),
        (1109, 118, 1400, 246, "VLM 调用成本", "$0.84", "−31%", AMBER),
    )
    for x1, y1, x2, y2, label, value, badge, accent in cards:
        card(canvas, (x1, y1, x2, y2), candidate=candidate)
        circle(canvas, (x1 + 26, y1 + 28), 6, fill=accent)
        text(canvas, (x1 + 40, y1 + 28), label, size=13, fill=MUTED, anchor="lm")
        text(canvas, (x1 + 22, y1 + 79), value, size=30, fill=INK, anchor="lm")
        rounded_rectangle(canvas, (x1 + 93, y1 + 66, x1 + 156, y1 + 91), radius=8, fill="#F4F5F8")
        text(canvas, (x1 + 124, y1 + 78), badge, size=10, fill=accent, anchor="mm")

    sparkline(
        canvas, [(449, 211), (464, 203), (479, 207), (494, 189), (510, 194), (526, 174)], TEAL
    )
    sparkline(canvas, [(724, 207), (739, 201), (754, 205), (769, 182), (785, 188), (801, 172)], RED)
    sparkline(
        canvas,
        [(999, 181), (1014, 188), (1029, 179), (1044, 193), (1060, 187), (1076, 198)],
        PURPLE,
    )
    sparkline(
        canvas,
        [(1308, 178), (1323, 184), (1338, 194), (1353, 190), (1369, 204), (1385, 209)],
        AMBER,
    )


def draw_chart(canvas: Image.Image, *, candidate: bool) -> None:
    card(canvas, (284, 272, 960, 566), candidate=candidate)
    text(canvas, (310, 305), "视觉回归趋势", size=17, fill=INK, anchor="lm")
    text(canvas, (310, 330), "最近 7 次构建", size=12, fill=MUTED, anchor="lm")
    rounded_rectangle(canvas, (813, 291, 933, 327), radius=10, fill="#F5F5F9")
    text(canvas, (873, 309), "最近 30 天", size=11, fill="#505769", anchor="mm")

    chart_left, chart_top, chart_right, chart_bottom = 326, 365, 925, 522
    for row in range(4):
        y = chart_top + row * (chart_bottom - chart_top) / 3
        line(canvas, [(chart_left, y), (chart_right, y)], fill="#EEF0F5", width=1)
        text(canvas, (313, y), str(24 - row * 8), size=9, fill="#9AA0AF", anchor="rm")
    labels = ("#36", "#37", "#38", "#39", "#40", "#41", "#42")
    xs = [350 + i * 91 for i in range(7)]
    for x, label in zip(xs, labels, strict=True):
        text(canvas, (x, 540), label, size=9, fill="#9AA0AF", anchor="mm")
    semantic = [
        (xs[0], 475),
        (xs[1], 460),
        (xs[2], 481),
        (xs[3], 431),
        (xs[4], 449),
        (xs[5], 409),
        (xs[6], 419),
    ]
    cosmetic = [
        (xs[0], 402),
        (xs[1], 420),
        (xs[2], 390),
        (xs[3], 404),
        (xs[4], 374),
        (xs[5], 396),
        (xs[6], 368),
    ]
    line(canvas, semantic, fill=RED, width=3)
    line(canvas, cosmetic, fill=PURPLE, width=3)
    for point in semantic:
        circle(canvas, point, 4, fill=SURFACE, outline=RED, width=2)
    for point in cosmetic:
        circle(canvas, point, 4, fill=SURFACE, outline=PURPLE, width=2)
    circle(canvas, (672, 307), 4, fill=RED)
    text(canvas, (683, 307), "语义回归", size=10, fill=MUTED, anchor="lm")
    circle(canvas, (746, 307), 4, fill=PURPLE)
    text(canvas, (757, 307), "无害变化", size=10, fill=MUTED, anchor="lm")


def issue_row(
    canvas: Image.Image,
    y: float,
    *,
    color: str,
    title: str,
    detail: str,
) -> None:
    circle(canvas, (1012, y), 15, fill=color)
    text(canvas, (1012, y), "!" if color == RED else "✓", size=12, fill="#FFFFFF", anchor="mm")
    text(canvas, (1040, y - 7), title, size=13, fill=INK, anchor="lm")
    text(canvas, (1040, y + 13), detail, size=10, fill=MUTED, anchor="lm")
    chevron(canvas, (1370, y), "#A0A5B2")


def draw_run_summary(canvas: Image.Image, *, candidate: bool) -> None:
    card(canvas, (980, 272, 1400, 566), candidate=candidate)
    text(canvas, (1006, 305), "本次检查", size=17, fill=INK, anchor="lm")
    rounded_rectangle(canvas, (1305, 291, 1374, 319), radius=9, fill="#E9F8F5")
    text(canvas, (1339, 305), "已完成", size=10, fill=TEAL, anchor="mm")

    issue_row(canvas, 365, color=RED, title="中文 CTA 文本被截断", detail="mobile-zh · /checkout")
    line(canvas, [(1006, 405), (1374, 405)], fill=LINE, width=1)
    issue_row(canvas, 442, color=RED, title="刷新控件缺少可见图标", detail="desktop-zh · /overview")
    line(canvas, [(1006, 482), (1374, 482)], fill=LINE, width=1)
    issue_row(canvas, 519, color=TEAL, title="卡片阴影调整", detail="cosmetic · 自动忽略")


def draw_clipped_cta(canvas: Image.Image, *, candidate: bool) -> None:
    box = (1146, 798, 1344, 842)
    rounded_rectangle(canvas, box, radius=12, fill=PURPLE)
    if not candidate:
        text(canvas, (1245, 820), "查看完整报告", size=14, fill="#FFFFFF", anchor="mm")
        return

    # Recreate a CSS overflow regression: the button keeps its dimensions, but a
    # too-narrow inner span clips the final Chinese characters.
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    text(layer, (1245, 820), "查看完整报告", size=14, fill="#FFFFFF", anchor="mm")
    clip = xy((1163, 798, 1269, 842))
    clipped = layer.crop(clip)
    canvas.alpha_composite(clipped, dest=(clip[0], clip[1]))


def draw_scenario_table(canvas: Image.Image, *, candidate: bool) -> None:
    card(canvas, (284, 592, 1400, 870), candidate=candidate)
    text(canvas, (310, 625), "关键场景", size=17, fill=INK, anchor="lm")
    text(canvas, (310, 650), "按用户影响排序的可审计证据", size=12, fill=MUTED, anchor="lm")
    rounded_rectangle(canvas, (1283, 612, 1374, 648), radius=10, fill="#F5F5F9")
    text(canvas, (1328, 630), "全部 128", size=11, fill="#505769", anchor="mm")

    line(canvas, [(310, 678), (1374, 678)], fill=LINE, width=1)
    headers = ((324, "场景"), (644, "变更类型"), (820, "置信度"), (964, "证据"))
    for x, label in headers:
        text(canvas, (x, 699), label, size=10, fill="#9298A7", anchor="lm")

    # Highest-risk row, with an embedded miniature viewport and CTA.
    rounded_rectangle(canvas, (308, 719, 1376, 853), radius=14, fill="#FBFBFD", outline="#F0F1F5")
    rounded_rectangle(canvas, (324, 738, 374, 834), radius=9, fill="#25263A")
    rounded_rectangle(canvas, (329, 744, 369, 828), radius=6, fill="#F7F5FF")
    rounded_rectangle(canvas, (334, 752, 364, 764), radius=3, fill="#E8E4FF")
    rounded_rectangle(canvas, (334, 771, 361, 777), radius=2, fill="#D9DCE7")
    rounded_rectangle(canvas, (334, 782, 356, 788), radius=2, fill="#E6E8EF")
    rounded_rectangle(canvas, (334, 805, 364, 819), radius=4, fill=PURPLE)
    text(canvas, (397, 765), "移动端结账", size=13, fill=INK, anchor="lm")
    text(canvas, (397, 789), "mobile-zh · 390 × 844", size=10, fill=MUTED, anchor="lm")
    rounded_rectangle(canvas, (644, 754, 736, 782), radius=9, fill="#FFE9ED")
    text(canvas, (690, 768), "严重回归", size=10, fill=RED, anchor="mm")
    text(canvas, (820, 768), "0.97", size=13, fill=INK, anchor="lm")
    rounded_rectangle(canvas, (964, 747, 1124, 793), radius=10, fill="#F1EFFF")
    text(canvas, (979, 762), "文本区域", size=9, fill=PURPLE_DARK, anchor="lm")
    text(canvas, (979, 780), "x=48 y=716 w=294", size=9, fill=MUTED, anchor="lm")
    draw_clipped_cta(canvas, candidate=candidate)


def render(candidate: bool) -> Image.Image:
    canvas = Image.new("RGBA", (WIDTH * SCALE, HEIGHT * SCALE), "#F7F8FB")
    draw_sidebar(canvas)
    draw_topbar(canvas, candidate=candidate)
    draw_metrics(canvas, candidate=candidate)
    draw_chart(canvas, candidate=candidate)
    draw_run_summary(canvas, candidate=candidate)
    draw_scenario_table(canvas, candidate=candidate)
    return canvas.convert("RGB").resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def write_assets(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline = output_dir / "baseline.png"
    candidate = output_dir / "candidate.png"
    render(candidate=False).save(baseline, format="PNG", optimize=False, compress_level=9)
    render(candidate=True).save(candidate, format="PNG", optimize=False, compress_level=9)
    return baseline, candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "examples",
        help="directory for baseline.png and candidate.png (default: examples/)",
    )
    args = parser.parse_args()
    baseline, candidate = write_assets(args.output_dir)
    selected_font = str(_font_path()) if _font_path() else "Pillow default bitmap font"
    print(f"font: {selected_font}")
    print(f"wrote: {baseline}")
    print(f"wrote: {candidate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
