"""自绘 SVG 图表引擎（16-bit 像素风）。

配色遵循 ENDESGA-32 色盘子集：
  #262b44 深蓝（卡片底）  #3a4466 暗蓝（网格）  #8b9bb4 银灰
  #c0cbdc 浅银（主数据）  #fee761 黄（强调/核心）  #e43b44 红（火热）
  #63c74d 绿（冷）        #f77622 橙            #0099db 蓝

设计约束：
  - 图表底色透明，由卡片提供 Bayer 抖动底纹
  - 文字使用浅色，保证在深色底上可读
  - 每元素带 <title> 提供原生 hover 数值
  - 热力图使用「绿→黄→橙→红」离散四档，映射冷热而非单色明度
"""
from __future__ import annotations

import math
from html import escape

# ---- 色盘 ----
DEEP = "#262b44"
DARK = "#3a4466"
SILVER = "#8b9bb4"
LIGHT = "#c0cbdc"
PAPER = "#ead4aa"
YELLOW = "#fee761"
RED = "#e43b44"
GREEN = "#63c74d"
ORANGE = "#f77622"
BLUE = "#0099db"
CRIMSON = "#a22633"

MUTED = SILVER
LINE = DARK
TEXT = PAPER

FONT = "font-family:'DotGothic16','Silkscreen',monospace"


def _esc(s) -> str:
    return escape(str(s or ""), quote=True)


def _wrap(svg: str, w: int, h: int, title: str) -> str:
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{_esc(title)}" '
        f'shape-rendering="crispEdges" '
        f'style="display:block;max-width:{w}px;margin:0 auto;{FONT}">'
        f"<title>{_esc(title)}</title>{svg}</svg>"
    )


def _short(name: str, limit: int = 9) -> str:
    name = str(name)
    return name if len(name) <= limit else name[: limit - 1] + "…"


def _text_w(s: str, size: float, fullwidth: bool = False) -> float:
    """估算文本像素宽度。

    DotGothic16 是等宽全角字体，中英文都占 1em，因此词云里按全角计算，
    避免估算偏小导致文字重叠。
    """
    if fullwidth:
        return len(s) * size
    w = 0.0
    for ch in s:
        w += size if ord(ch) > 0x2E80 else size * 0.58
    return w


# ---------------- 横向条形 ----------------

def hbar(data: list[dict], title: str, unit: str = "", w: int | None = None,
         highlight: set[str] | None = None, label_w: int = 132,
         label_limit: int = 9) -> str:
    if not data:
        return _empty(title)
    highlight = highlight or set()
    row_h, pad_t, pad_b = 24, 8, 10
    w = w or 680
    h = pad_t + row_h * len(data) + pad_b
    max_v = max(d["value"] for d in data) or 1
    bar_x = label_w
    bar_max = w - bar_x - 66

    pid, pat_svg = _scan_pattern()
    parts = [f"<defs>{pat_svg}</defs>"]
    for i, d in enumerate(data):
        y = pad_t + i * row_h
        val = d["value"]
        bw = max(3, bar_max * val / max_v)
        is_hl = d.get("key") in highlight
        color = YELLOW if is_hl else SILVER
        tip = f"{d['name']}：{val:g}{unit}" + (f"（{d['sub']}）" if d.get("sub") else "")
        parts.append(
            f'<g><title>{_esc(tip)}</title>'
            f'<text x="{label_w - 8}" y="{y + 15}" text-anchor="end" font-size="11" '
            f'fill="{LIGHT}">{_esc(_short(d["name"], label_limit))}</text>'
            f'{_pixel_bar(bar_x, y + 5, bw, 11, color, pid, radius=1)}'
            f'<text x="{bar_x + bw + 8:.0f}" y="{y + 15}" font-size="10" '
            f'fill="{PAPER}">{val:g}{_esc(unit)}</text>'
            f"</g>"
        )
    return _wrap("".join(parts), w, h, title)


# ---------------- 多序列折线（像素阶梯线） ----------------

def multiline(series: list[dict], weeks: list[str], title: str,
              w: int = 680, h: int = 250) -> str:
    if not weeks or not series:
        return _empty(title)
    pad_l, pad_r, pad_t, pad_b = 46, 104, 12, 26
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    n = len(weeks)
    all_v = [v for s in series for v in s["values"]]
    max_v = max(all_v) if all_v and max(all_v) > 0 else 1.0

    def x(i: int) -> float:
        return pad_l + (plot_w * i / max(1, n - 1) if n > 1 else plot_w / 2)

    def y(v: float) -> float:
        return pad_t + plot_h - plot_h * v / max_v

    parts = []
    for k in range(5):
        v = max_v * k / 4
        yy = y(v)
        # 虚线网格，像素风用短划
        parts.append(f'<line x1="{pad_l}" y1="{yy:.0f}" x2="{pad_l + plot_w}" y2="{yy:.0f}" '
                     f'stroke="{DARK}" stroke-width="1" stroke-dasharray="2 3"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{yy + 3:.0f}" text-anchor="end" font-size="9" '
                     f'fill="{SILVER}">{v:.0f}</text>')
    step = max(1, n // 8)
    for i in range(0, n, step):
        parts.append(f'<text x="{x(i):.0f}" y="{h - 8}" text-anchor="middle" font-size="9" '
                     f'fill="{SILVER}">W{weeks[i].split("-W")[-1]}</text>')

    palette = [YELLOW, BLUE, GREEN, RED, ORANGE, PAPER]
    for si, s in enumerate(series):
        color = s.get("color") or palette[si % len(palette)]
        # 阶梯线：像素风不用斜线，用水平+垂直段
        pts = []
        for i, v in enumerate(s["values"]):
            if i == 0:
                pts.append(f"M{x(i):.0f},{y(v):.0f}")
            else:
                pts.append(f"H{x(i):.0f}")
                pts.append(f"V{y(v):.0f}")
        parts.append(f'<path d="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2"/>')
        for i, v in enumerate(s["values"]):
            parts.append(
                f'<g><title>{_esc(s["name"])} · {weeks[i]}：{v:g}</title>'
                f'<rect x="{x(i) - 2:.0f}" y="{y(v) - 2:.0f}" width="4" height="4" fill="{color}"/></g>'
            )
        if s["values"]:
            parts.append(
                f'<text x="{x(n - 1) + 8:.0f}" y="{y(s["values"][-1]) + 4:.0f}" '
                f'font-size="10" fill="{color}">{_esc(_short(s["name"], 8))}</text>'
            )
    return _wrap("".join(parts), w, h, title)


# ---------------- 热力矩阵（绿→黄→橙→红 离散四档） ----------------

HEAT_STEPS = [GREEN, YELLOW, ORANGE, RED]


def _heat_color(v: float | None, max_v: float) -> str | None:
    if v is None:
        return None
    if v <= 0:
        return GREEN
    t = min(0.999, v / max_v)
    return HEAT_STEPS[int(t * 4)]


def heatmap(rows: list[dict], weeks: list[str], matrix: list[list[float | None]],
            title: str, w: int = 680) -> str:
    if not rows or not weeks:
        return _empty(title)
    label_w, pad_t = 138, 24
    cell_h, gap = 18, 3
    h = pad_t + len(rows) * (cell_h + gap) + 10
    cell_w = (w - label_w - 10) / max(1, len(weeks))

    flat = [v for r in matrix for v in r if v]
    max_v = max(flat) if flat else 1.0

    parts = [f'<text x="{label_w - 8}" y="15" text-anchor="end" font-size="9" '
             f'fill="{SILVER}">赛道 \\ 周</text>']
    for c, wk in enumerate(weeks):
        parts.append(
            f'<text x="{label_w + c * cell_w + cell_w / 2:.0f}" y="15" text-anchor="middle" '
            f'font-size="9" fill="{SILVER}">W{wk.split("-W")[-1]}</text>'
        )
    for r, row in enumerate(rows):
        y = pad_t + r * (cell_h + gap)
        weight = "700" if row.get("is_focus") else "400"
        fill = YELLOW if row.get("is_focus") else LIGHT
        parts.append(
            f'<text x="{label_w - 8}" y="{y + cell_h / 2 + 4:.0f}" text-anchor="end" '
            f'font-size="11" font-weight="{weight}" fill="{fill}">{_esc(_short(row["name"]))}</text>'
        )
        for c in range(len(weeks)):
            v = matrix[r][c]
            xx = label_w + c * cell_w
            color = _heat_color(v, max_v)
            if color is None:
                # 无数据：留空，只画暗色网格格
                parts.append(f'<rect x="{xx + 1:.0f}" y="{y}" width="{cell_w - 2:.0f}" '
                             f'height="{cell_h}" fill="none" stroke="{DARK}" stroke-width="1"/>')
                tip = f'{row["name"]} · {weeks[c]}：无数据'
            else:
                parts.append(f'<rect x="{xx + 1:.0f}" y="{y}" width="{cell_w - 2:.0f}" '
                             f'height="{cell_h}" fill="{color}"/>')
                tip = f'{row["name"]} · {weeks[c]}：活跃度 {v:g}'
            parts.append(f'<g><title>{_esc(tip)}</title></g>')

    # 色阶图例
    ly = h - 2
    legend = []
    labels = [("冷", GREEN), ("偏冷", YELLOW), ("偏热", ORANGE), ("火热", RED)]
    lx = label_w
    for name, col in labels:
        legend.append(f'<rect x="{lx}" y="{ly - 10}" width="10" height="10" fill="{col}"/>'
                      f'<text x="{lx + 14}" y="{ly - 1}" font-size="9" fill="{SILVER}">{name}</text>')
        lx += 56
    legend.append(f'<rect x="{lx}" y="{ly - 10}" width="10" height="10" fill="none" '
                  f'stroke="{DARK}"/>'
                  f'<text x="{lx + 14}" y="{ly - 1}" font-size="9" fill="{SILVER}">无数据</text>')
    return _wrap("".join(parts) + "".join(legend), w, h + 12, title)


# ---------------- 环比（分歧条形） ----------------

def _pct(v: float) -> str:
    a = abs(v)
    if a >= 999:
        return f"{v / 100:+.1f} 倍"
    return f"{v:+.0f}%"


def diverging(data: list[dict], title: str, w: int = 680) -> str:
    if not data:
        return _empty(title)
    row_h, pad_t = 24, 20
    h = pad_t + row_h * len(data) + 16
    label_w = 126
    mid = label_w + (w - label_w) / 2
    max_abs = max(abs(d["value"]) for d in data) or 1
    half = (w - label_w) / 2 - 56

    parts = [f'<line x1="{mid:.0f}" y1="{pad_t - 8}" x2="{mid:.0f}" y2="{h - 12}" '
             f'stroke="{DARK}" stroke-width="1"/>']
    for i, d in enumerate(data):
        y = pad_t + i * row_h
        v = d["value"]
        bw = max(3.0, half * abs(v) / max_abs)
        is_up = v >= 0
        color = RED if is_up else GREEN
        parts.append(
            f'<g><title>{_esc(d["name"])}：{v:+.1f}%</title>'
            f'<text x="{label_w - 10}" y="{y + 14}" text-anchor="end" font-size="10" '
            f'fill="{LIGHT}">{_esc(_short(d["name"], 10))}</text>'
            f'<rect x="{mid if is_up else mid - bw:.0f}" y="{y + 5}" width="{bw:.0f}" '
            f'height="10" fill="{color}"/>'
            f'<text x="{(mid + bw + 6) if is_up else (mid - bw - 6):.0f}" y="{y + 14}" '
            f'text-anchor="{"start" if is_up else "end"}" font-size="9" fill="{color}">'
            f'{"▲" if is_up else "▼"}{_esc(_pct(v).lstrip("+-"))}</text>'
            f"</g>"
        )
    return _wrap("".join(parts), w, h, title)


# ---------------- 词云（螺旋布局 + 矩形碰撞） ----------------

CLOUD_COLORS = [RED, ORANGE, YELLOW, BLUE, LIGHT, SILVER]


def wordcloud(words: list[dict], title: str, w: int = 680, h: int = 400,
              limit: int = 52, search_url: str = "search.html") -> str:
    """按出现条数排行渲染词云。

    布局：由内向外螺旋，字号分四档；宽度按全角字符估算，保证中文英文都不重叠。
    """
    if not words:
        return _empty(title)
    words = words[:limit]
    max_c = words[0]["count"]
    min_c = words[-1]["count"]
    span = max(1, max_c - min_c)

    def size_of(c: int) -> int:
        """五档字号，刻意拉大首尾差距：最大 40px / 最小 10px = 4 倍。"""
        r = (c - min_c) / span
        if r > 0.90:
            return 40
        if r > 0.72:
            return 29
        if r > 0.50:
            return 21
        if r > 0.26:
            return 15
        return 10

    placed: list[tuple[float, float, float, float]] = []
    parts: list[str] = []
    cx, cy = w / 2, h / 2
    pad = 4

    def overlaps(x, y, tw, th):
        for px, py, pw, ph in placed:
            if (x < px + pw + pad and x + tw + pad > px
                    and y < py + ph + pad and y + th + pad > py):
                return True
        return False

    for idx, wd in enumerate(words):
        text = wd["name"]
        size = size_of(wd["count"])
        tw = _text_w(text, size, fullwidth=True)
        th = size * 1.25
        color = CLOUD_COLORS[min(idx // 5, len(CLOUD_COLORS) - 1)]

        spot = None
        # 半径按 sqrt 增长：内侧密、外侧疏，符合词云视觉重心
        for step in range(1, 2400):
            angle = 0.5 * step
            radius = 8.6 * (step ** 0.63)
            x = cx + radius * math.cos(angle) - tw / 2
            y = cy + radius * 0.72 * math.sin(angle) - th / 2
            if x < pad or y < pad or x + tw > w - pad or y + th > h - pad:
                continue
            if overlaps(x, y, tw, th):
                continue
            spot = (x, y)
            break
        if not spot:
            continue
        x, y = spot
        placed.append((x, y, tw, th))
        tip = f"{text}：{wd['count']} 条新闻提及 · 点击检索"
        parts.append(
            f'<g class="cw" role="link" tabindex="0" '
            f"onclick=\"location.href='{search_url}?q={_esc(text)}'\" "
            f'style="cursor:inherit"><title>{_esc(tip)}</title>'
            f'<text class="cw-shadow" x="{x + 1:.0f}" y="{y + size:.0f}" font-size="{size}" '
            f'fill="{DEEP}" font-family="DotGothic16,monospace">{_esc(text)}</text>'
            f'<text class="cw-main" x="{x:.0f}" y="{y + size - 1:.0f}" font-size="{size}" '
            f'fill="{color}" font-family="DotGothic16,monospace">{_esc(text)}</text></g>'
        )
    return _wrap("".join(parts), w, h, title)


# ---------------- 真实厂商图标（12x12 像素化后的 PNG，base64 内嵌） ----------------
# 来源：icons8 公开图标，缩样到 12x12 并二值化 alpha，浏览器按 nearest-neighbour 放大
PIXEL_ICONS = {
    "Google": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAwAAAAMCAYAAABWdVznAAABDElEQVR42qWRsUoDARBE327ukhMkErDyC8QgCBZiZSccaGzFSvAb/AVFaz/AWgtJtBGxUCxt7K0sEixEONQkd0nGQrkYQUScbpaZ3RkW/gj7PtAyIv0kIdjFqCYnihEZICADmWEhUAA7V67z3NoFOkAEdo35lYySRsTDGDdF6TCUaq7fOgQAg76haSdoZPm2qe07mTsMevQ9osgbD3vzFgC4BN3e6FUTckCGFQIYfO1gcDleZaMe55Fa+3PW2p21CX/FozJFT4cGW0rtIKmSWMTm6dC0VY9lYx3UN+53Fi3vAFB+fqJdqfBSiKidrAmcZDJkZuGY5u0jzZ8et362qnb2kbQUiqOVhvEfvAOFOFmnl51ZDAAAAABJRU5ErkJggg==",
    "Anthropic": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAwAAAAMCAYAAABWdVznAAAA/UlEQVR42tWQsU4CQRRFzxuGWSasBOhspOdbqKXRgo8ghsIQ46dowVfwEyZIbUO3jWx0Z2fnWawQ/ARfdZObm3fvgf9/chKHp3v9/I7UMWKMASClRNdarnqW6/WLABiA/WquI9/DiDDue4Y+Y+gzxn2PEWHke+xXcz0HctdldyhYbLaUVU1RVhRlRVnVLDZbdoeC3HUBsAAhJgbeMZtOSCjyWzShzKYTBt4RYmo37B5uFcCZDs52OFbhYpqSZ44QG0Jq2g+iAgLOGuom4Z3FWwvAV4zUTWq9kEAvKH083ukxBAQ5V1IFRcmd4+b5Vf7wfVu21d6XLY1LffIAfgAhE2NFr4a/hQAAAABJRU5ErkJggg==",
    "OpenAI": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAwAAAAMCAYAAABWdVznAAAASUlEQVR42o1SQRIAQAQq//9ze18FJ2NIBeBDoQ6GRn5DTKgyud2YmtsQF/40VBuKhs0oI3AySBty01CBLy930cViLg5pOtzpPR7Wnyfqnz6O7gAAAABJRU5ErkJggg==",
    "xAI": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAwAAAAMCAYAAABWdVznAAAAQUlEQVR42rVQMRIAIAiCrv9/2da8hByKEQUR4CMCAKYabGDBpeVw3Cicaa4lgYpGJ6Bb7uS3P6DR2FGrqpBXp2dYGYISBlr0vjQAAAAASUVORK5CYII=",
    "深度求索 DeepSeek": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAwAAAAMCAYAAABWdVznAAABUElEQVR42rWRyytEcRzFP7+foRnGlORmMx55RFaTyVhRFDYyyTOxsJGdP8BC+TcsbDw28iqUjZXGe+G5spAQQ6R079x7f18rysaKszqbU+dzDvy31JfpGT4Rz3MBhVLC8nyDAkgOpGRlsVH9CHT2HUooN4JSLsYXRAQxGZbm6lVycE+0zkHExxgf3T2UEssK4ThpntOvuO4Hnv8BOkJb166sLCQUCkRgdTGhAqXRINOTFTy/uGxuP7C+9YQx0NGa4fXNQmelRDyHr1r68cnGGE1JNMzYaCUT42U4js/NbYaW5lzyw/kI+hs6q7B4ZKrIClNbnYdtG6qrIhjjsbaR5vzyHa1zWJqLfUMHdjabVEHBvpSXhqirCTIze01/T5T7B5uDk2yM//Jj1gDA8nyDEo4kHrM4OLY5u7ojEY9wenGP7eT9fkzv8LG0J1PyZ09/Ajphi+6fSH/7AAAAAElFTkSuQmCC",
}

_PAT_SEQ = [0]


def _mix(hex_color: str, target: str, ratio: float) -> str:
    """按比例把颜色向 target 混合，用于生成柱体高光/阴影（不透明，避免羽化）。"""
    c1 = hex_color.lstrip("#")
    c2 = target.lstrip("#")
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = round(r1 + (r2 - r1) * ratio)
    g = round(g1 + (g2 - g1) * ratio)
    b = round(b1 + (b2 - b1) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"


def _lighten(c: str, r: float = 0.34) -> str:
    return _mix(c, "#ffffff", r)


def _darken(c: str, r: float = 0.38) -> str:
    return _mix(c, "#000000", r)


def _scan_pattern(line_color: str = DEEP) -> tuple[str, str]:
    """6px 周期的扫描线 pattern，给柱体加能量条质感（不能太抢主体色）。"""
    _PAT_SEQ[0] += 1
    pid = f"scan{_PAT_SEQ[0]}"
    svg = (f'<pattern id="{pid}" width="6" height="6" patternUnits="userSpaceOnUse">'
           f'<rect width="6" height="1" fill="{line_color}"/></pattern>')
    return pid, svg


def _pixel_bar(x: float, y: float, w: float, h: float, color: str,
               pid: str, radius: int = 2, scan: str | None = None) -> str:
    """16-bit 立体柱体：主色 + 顶/左高光 + 右/底阴影 + 扫描线。"""
    if h < 4 or w < 4:
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{color}"/>'
    hi, lo = _lighten(color), _darken(color)
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{color}"/>'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="url(#{pid})" opacity="0.999"/>'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{radius}" fill="{hi}"/>'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{radius}" height="{h - radius:.1f}" fill="{hi}"/>'
        f'<rect x="{x + w - radius:.1f}" y="{y + radius:.1f}" width="{radius}" '
        f'height="{h - radius:.1f}" fill="{lo}"/>'
        f'<rect x="{x + radius:.1f}" y="{y + h - radius:.1f}" width="{w - radius:.1f}" '
        f'height="{radius}" fill="{lo}"/>'
    )


# ---------------- 厂商像素图标与品牌色 ----------------
# 8x8 字符画，最近邻放大；颜色取自 ENDESGA-32，尽量贴近各家品牌色且互相可区分
VENDOR_STYLE = {
    "OpenAI": ("#c0cbdc", [
        "..####..", ".#....#.", "#..##..#", "#.#..#.#",
        "#..##..#", ".#....#.", "..####..", "........"]),
    "Anthropic": ("#d77643", [
        "...#....", ".#.#.#..", "..###...", "#######.",
        "..###...", ".#.#.#..", "...#....", "........"]),
    "Google": ("#0099db", [
        "..####..", ".#....#.", "#.......", "#..###..",
        "#....#..", ".#...##.", "..####..", "........"]),
    "Meta": ("#2ce8f5", [
        "........", "........", ".##..##.", "#..#..#.",
        "#..#..#.", ".##..##.", "........", "........"]),
    "xAI": ("#8b9bb4", [
        "#......#", ".#....#.", "..#..#..", "...##...",
        "...##...", "..#..#..", ".#....#.", "#......#"]),
    "Mistral": ("#f77622", [
        "#.#.#.#.", "#.#.#.#.", "#.#.#.#.", "#.#.#.#.",
        "#.#.#.#.", "#.#.#.#.", "#.#.#.#.", "#.#.#.#."]),
    "阿里 Qwen": ("#b55088", [
        ".####...", "#....#..", "#....#..", "#....#..",
        "#....#..", "#....#..", ".####.#.", "......#."]),
    "月之暗面 Kimi": ("#feae34", [
        "..####..", ".#..#...", "#...#...", "#.......",
        "#.......", "#....#..", ".#..#...", "..####.."]),
    "智谱 GLM": ("#63c74d", [
        "########", "......#.", ".....#..", "....#...",
        "...#....", "..#.....", ".#......", "########"]),
    "深度求索 DeepSeek": ("#5a6988", [
        "........", "........", "..####..", ".#....#.",
        "........", "#.#.#.#.", ".#.#.#.#", "........"]),
    "MiniMax": ("#e43b44", [
        "#......#", "##....##", "#.#..#.#", "#..##..#",
        "#......#", "#......#", "#......#", "........"]),
    "字节豆包": ("#ead4aa", [
        "..####..", ".#....#.", "#..##..#", "#..##..#",
        "#......#", ".#....#.", "..####..", "........"]),
    "腾讯混元": ("#3e8948", [
        "........", ".######.", "#..##..#", "#...#..#",
        "#..##..#", ".######.", "........", "........"]),
    "百度文心": ("#0099db", [
        "..#..#..", ".#.##.#.", "#..##..#", "########",
        "#..##..#", ".#.##.#.", "..#..#..", "........"]),
}


def _vendor_of(name: str, vendor: str) -> str:
    return vendor if vendor in VENDOR_STYLE else "OpenAI"


def _icon_svg(vendor: str, x: float, y: float, px: float) -> str:
    """绘制图标。

    结构必须是「定位层 + 动画层」两层：
      <g class="bar-slot" transform="translate(x,y)">   ← 定位，永不被动画覆盖
        <g class="bar-icon">...                        ← 动画层，hover 时跳动
    否则 CSS transform 会覆盖 SVG 的 transform 属性，图标会跳到画布左上角。
    """
    if vendor in PIXEL_ICONS:
        inner = (f'<image width="{px:.1f}" height="{px:.1f}" '
                 f'href="{PIXEL_ICONS[vendor]}" style="image-rendering:pixelated"/>')
    else:
        color, art = VENDOR_STYLE[_vendor_of("", vendor)]
        cell = px / 8.0
        inner = "".join(
            f'<rect x="{c * cell:.2f}" y="{r * cell:.2f}" width="{cell:.2f}" '
            f'height="{cell:.2f}" fill="{color}"/>'
            for r, row in enumerate(art)
            for c, ch in enumerate(row) if ch == "#"
        )
    return (f'<g class="bar-slot" transform="translate({x:.1f},{y:.1f})">'
            f'<g class="bar-icon">{inner}</g></g>')


def _split2(name: str, maxlen: int = 8) -> list[str]:
    """把模型名拆成两行，用于水平轴标签。"""
    name = name.strip()
    if len(name) <= maxlen:
        return [name]
    words = name.split()
    if len(words) <= 1:
        return [name[:maxlen], name[maxlen:maxlen * 2]]
    best_i, best_diff = 1, 10 ** 9
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        diff = abs(len(a) - len(b))
        if diff < best_diff:
            best_i, best_diff = i, diff
    return [" ".join(words[:best_i]), " ".join(words[best_i:])]


# ---------------- 竖向柱状图（跑分排行） ----------------

def vbar(data: list[dict], title: str, demo: bool = False,
         w: int = 960, h: int = 380, unit: str = "", value_fmt: str = "{:.0f}") -> str:
    """竖向柱状图：柱宽撑满，柱顶厂商图标，水平两行轴标签，柱体带 16-bit 立体高光。

    data: [{name, value, vendor}]
    """
    if not data:
        return _empty(title)

    n = len(data)
    pad_l, pad_r = 34, 8
    pad_t, pad_b = 42, 44
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    gap = 4.0
    bar_w = max(10.0, (plot_w - gap * (n - 1)) / n)

    max_v = max(d["value"] for d in data) or 1
    step = 10 if max_v > 40 else 5 if max_v > 10 else 1
    top_v = int((max_v // step + 1) * step)

    def y_of(v: float) -> float:
        return pad_t + plot_h - plot_h * v / top_v

    parts: list[str] = []
    defs: list[str] = []

    # 网格与刻度
    ticks = 4
    for i in range(ticks + 1):
        v = top_v * i / ticks
        yy = y_of(v)
        parts.append(f'<line x1="{pad_l}" y1="{yy:.0f}" x2="{pad_l + plot_w}" y2="{yy:.0f}" '
                     f'stroke="{DARK}" stroke-width="1" stroke-dasharray="2 3"/>')
        parts.append(f'<text x="{pad_l - 6}" y="{yy + 3:.0f}" text-anchor="end" font-size="9" '
                     f'fill="{SILVER}">{v:.0f}</text>')

    for i, d in enumerate(data):
        vendor = d.get("vendor", "")
        color, _art = VENDOR_STYLE[_vendor_of(d["name"], vendor)]
        x = pad_l + i * (bar_w + gap)
        bh = max(3.0, plot_h * d["value"] / top_v)
        by = pad_t + plot_h - bh
        cx = x + bar_w / 2

        tip = f'{d["name"]}（{vendor}）：{value_fmt.format(d["value"])}{unit}'

        # 每根柱一条与自身主色协调的扫描线，避免统一深蓝把柱体染灰
        pid, pat_svg = _scan_pattern(_mix(color, "#000000", 0.22))
        defs.append(pat_svg)

        parts.append(f'<g class="vbar"><title>{_esc(tip)}</title>')

        # 立体柱体
        parts.append(_pixel_bar(x, by, bar_w, bh, color, pid, radius=2))

        # 柱顶图标（可放大到 30px）
        icon_px = min(bar_w - 12, 30)
        parts.append(_icon_svg(vendor, cx - icon_px / 2, by - icon_px - 8, icon_px))

        # 数值：柱内顶部；柱太矮则移到柱顶上方
        label = value_fmt.format(d["value"])
        if bh > 20:
            # 白字 + 深色描边：在任意品牌色柱体上都清晰
            parts.append(f'<text x="{cx:.1f}" y="{by + 15:.1f}" text-anchor="middle" '
                         f'font-size="11" fill="#ffffff" stroke="{DEEP}" stroke-width="2" '
                         f'paint-order="stroke" font-weight="700">{_esc(label)}</text>')
        else:
            parts.append(f'<text x="{cx:.1f}" y="{by - 6:.1f}" text-anchor="middle" '
                         f'font-size="10" fill="{PAPER}">{_esc(label)}</text>')

        # 水平两行轴标签：保留完整型号名，靠拆行而不是删词来控制宽度
        lines = _split2(d["name"], 8)
        base = pad_t + plot_h + 14
        spans = f'<tspan x="{cx:.1f}" y="{base}">{_esc(lines[0])}</tspan>'
        if len(lines) > 1:
            spans += f'<tspan x="{cx:.1f}" y="{base + 11}">{_esc(lines[1])}</tspan>'
        parts.append(f'<text text-anchor="middle" font-size="9" fill="{PAPER}">{spans}</text>')

        parts.append("</g>")

    # defs 必须放在最前，否则 pattern 引用可能失效
    return _wrap(f"<defs>{''.join(defs)}</defs>" + "".join(parts), w, h, title)


# ---------------- 分段条（市场/类型占比） ----------------

SEG_COLORS = [BLUE, YELLOW, GREEN, ORANGE, SILVER, RED]


def segbar(parts_data: list[dict], title: str, w: int = 680) -> str:
    """单条分段比例条，像素方块拼接，带图例。"""
    parts_data = [p for p in parts_data if p["value"] > 0]
    total = sum(p["value"] for p in parts_data) or 1
    if not parts_data:
        return _empty(title)
    bar_h, pad_t = 18, 6
    x = 0.0
    seg = []
    for i, p in enumerate(parts_data):
        width = w * p["value"] / total
        color = SEG_COLORS[i % len(SEG_COLORS)]
        pct = p["value"] / total * 100
        seg.append(
            f'<g><title>{_esc(p["name"])}：{p["value"]:g} 条（{pct:.0f}%）</title>'
            f'<rect x="{x:.0f}" y="{pad_t}" width="{max(0, width - 1):.0f}" height="{bar_h}" fill="{color}"/>'
            + (f'<text x="{x + width / 2:.0f}" y="{pad_t + 13}" text-anchor="middle" '
               f'font-size="9" fill="{DEEP}">{pct:.0f}%</text>' if width > 40 else "")
            + "</g>"
        )
        x += width

    legend, lx = [], 0
    for i, p in enumerate(parts_data):
        color = SEG_COLORS[i % len(SEG_COLORS)]
        label = f'{p["name"]} {p["value"]:g}'
        legend.append(f'<rect x="{lx}" y="{pad_t + bar_h + 8}" width="8" height="8" fill="{color}"/>'
                      f'<text x="{lx + 12}" y="{pad_t + bar_h + 16}" font-size="9" '
                      f'fill="{SILVER}">{_esc(_short(label, 12))}</text>')
        lx += 22 + _text_w(label, 9) + 10
    return _wrap("".join(seg) + "".join(legend), w, pad_t + bar_h + 26, title)


def _empty(title: str) -> str:
    return _wrap(
        f'<rect x="0" y="0" width="680" height="70" fill="{DEEP}" stroke="{DARK}"/>'
        f'<text x="340" y="40" text-anchor="middle" font-size="11" fill="{SILVER}">NO DATA</text>',
        680, 70, title,
    )
