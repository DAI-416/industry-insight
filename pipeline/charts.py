"""自绘 SVG 图表引擎。无外部依赖，构建期生成静态图。

设计约束（PRD §7.1）：
  - 单色系为主色渐变，禁用彩虹色
  - 每个元素带 <title> 提供原生 hover 数值
  - viewBox + width:100% 自适应，移动端不溢出
  - 数值标签直接标注，不单纯依赖颜色
"""
from __future__ import annotations

from html import escape

INK = "#1B3A5C"
INK_2 = "#3E5871"
INK_3 = "#5A7893"
INK_4 = "#8AA7BF"
INK_5 = "#C5D3DE"
MUTED = "#8C8C8C"
LINE = "#E3E8ED"
TEXT = "#24313D"
CRIT = "#B03030"
WARN = "#C98A2E"

FONT = "font-family:'PingFang SC',-apple-system,sans-serif"


def _esc(s: str) -> str:
    return escape(str(s), quote=True)


def _short(name: str, limit: int = 9) -> str:
    """图表轴标签截断：超过 limit 个字符则省略，完整名称放在 hover title 里。"""
    name = str(name)
    return name if len(name) <= limit else name[: limit - 1] + "…"


def _wrap(svg: str, w: int, h: int, title: str) -> str:
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{_esc(title)}" '
        f'style="display:block;max-width:{w}px;margin:0 auto;{FONT}">'
        f"<title>{_esc(title)}</title>{svg}</svg>"
    )


# ---------------- V1/V8/V9/V10 横向条形 ----------------

def hbar(data: list[dict], title: str, unit: str = "", w: int | None = None,
         highlight: set[str] | None = None, label_w: int = 132) -> str:
    """data: [{name, value, sub?}] 已按需排序"""
    if not data:
        return _empty(title)
    highlight = highlight or set()
    row_h, pad_t, pad_b = 26, 10, 12
    w = w or 680
    h = pad_t + row_h * len(data) + pad_b
    max_v = max(d["value"] for d in data) or 1
    bar_x = label_w
    bar_max = w - bar_x - 62

    parts = []
    for i, d in enumerate(data):
        y = pad_t + i * row_h
        val = d["value"]
        bw = max(2, bar_max * val / max_v)
        color = INK if (d.get("key") in highlight or not highlight) else INK_4
        label = _esc(_short(d["name"]))
        tip = f"{d['name']}：{val:g}{unit}" + (f"（{d['sub']}）" if d.get("sub") else "")
        parts.append(
            f'<g><title>{_esc(tip)}</title>'
            f'<text x="{label_w - 8}" y="{y + 15}" text-anchor="end" font-size="12" fill="{TEXT}">{label}</text>'
            f'<rect x="{bar_x}" y="{y + 5}" width="{bw:.1f}" height="14" rx="2" fill="{color}"/>'
            f'<text x="{bar_x + bw + 8:.1f}" y="{y + 16}" font-size="11.5" fill="{MUTED}">{val:g}{_esc(unit)}</text>'
            f"</g>"
        )
    return _wrap("".join(parts), w, h, title)


# ---------------- V2 多序列折线 ----------------

def multiline(series: list[dict], weeks: list[str], title: str,
              w: int = 680, h: int = 260) -> str:
    """series: [{name, key, values: [float], color?}]"""
    if not weeks or not series:
        return _empty(title)
    pad_l, pad_r, pad_t, pad_b = 44, 96, 14, 26
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    n = len(weeks)
    all_v = [v for s in series for v in s["values"]]
    max_v = max(all_v) if all_v and max(all_v) > 0 else 1.0

    def x(i: int) -> float:
        return pad_l + (plot_w * i / max(1, n - 1) if n > 1 else plot_w / 2)

    def y(v: float) -> float:
        return pad_t + plot_h - plot_h * v / max_v

    parts = []
    # 网格与 y 轴刻度
    for k in range(5):
        v = max_v * k / 4
        yy = y(v)
        parts.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{pad_l + plot_w}" y2="{yy:.1f}" stroke="{LINE}" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{yy + 4:.1f}" text-anchor="end" font-size="10.5" fill="{MUTED}">{v:.0f}</text>')
    # x 轴标签（最多 8 个，均匀抽样）
    step = max(1, n // 8)
    for i in range(0, n, step):
        wk = weeks[i].split("-W")[-1]
        parts.append(f'<text x="{x(i):.1f}" y="{h - 8}" text-anchor="middle" font-size="10.5" fill="{MUTED}">W{wk}</text>')

    palette = [INK, INK_3, INK_4, CRIT, WARN]
    for si, s in enumerate(series):
        color = s.get("color") or palette[si % len(palette)]
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(s["values"]))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for i, v in enumerate(s["values"]):
            parts.append(
                f'<g><title>{_esc(s["name"])} · {weeks[i]}：{v:g}</title>'
                f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.8" fill="{color}"/></g>'
            )
        # 末尾直接标注序列名，省去图例
        if s["values"]:
            parts.append(
                f'<text x="{x(n - 1) + 8:.1f}" y="{y(s["values"][-1]) + 4:.1f}" '
                f'font-size="11" fill="{color}">{_esc(s["name"])}</text>'
            )
    return _wrap("".join(parts), w, h, title)


# ---------------- V3 赛道×周 热力矩阵 ----------------

def heatmap(rows: list[dict], weeks: list[str], matrix: list[list[float | None]],
            title: str, w: int = 680) -> str:
    """rows: [{name, is_focus}]；matrix[r][c] 为 None 表示该周无数据（留白）。"""
    if not rows or not weeks:
        return _empty(title)
    label_w, pad_t = 132, 22
    cell_h, gap = 17, 3
    h = pad_t + len(rows) * (cell_h + gap) + 8
    cell_w = (w - label_w - 8) / max(1, len(weeks))

    flat = [v for r in matrix for v in r if v is not None]
    max_v = max(flat) if flat else 1.0

    def shade(v: float | None) -> str:
        if v is None or v <= 0:
            return "#FFFFFF"
        t = min(1.0, v / max_v)
        # 主色从浅到深插值
        r0, g0, b0 = (197, 211, 222)
        r1, g1, b1 = (27, 58, 92)
        return f"rgb({int(r0 + (r1 - r0) * t)},{int(g0 + (g1 - g0) * t)},{int(b0 + (b1 - b0) * t)})"

    parts = [f'<text x="{label_w - 8}" y="14" text-anchor="end" font-size="10" fill="{MUTED}">赛道 \\ 周</text>']
    for c, wk in enumerate(weeks):
        parts.append(
            f'<text x="{label_w + c * cell_w + cell_w / 2:.1f}" y="14" text-anchor="middle" '
            f'font-size="10" fill="{MUTED}">W{wk.split("-W")[-1]}</text>'
        )
    for r, row in enumerate(rows):
        y = pad_t + r * (cell_h + gap)
        weight = "600" if row.get("is_focus") else "400"
        fill = INK if row.get("is_focus") else TEXT
        parts.append(
            f'<text x="{label_w - 8}" y="{y + cell_h / 2 + 4:.1f}" text-anchor="end" '
            f'font-size="11.5" font-weight="{weight}" fill="{fill}">{_esc(_short(row["name"]))}</text>'
        )
        for c in range(len(weeks)):
            v = matrix[r][c]
            xx = label_w + c * cell_w
            color = shade(v)
            stroke = LINE if v else "#F0F3F6"
            tip = f'{row["name"]} · {weeks[c]}：' + ("无数据" if v is None else f"活跃度 {v:g}")
            parts.append(
                f'<g><title>{_esc(tip)}</title>'
                f'<rect x="{xx + 1:.1f}" y="{y}" width="{cell_w - 2:.1f}" height="{cell_h}" '
                f'rx="2" fill="{color}" stroke="{stroke}" stroke-width="1"/></g>'
            )
    return _wrap("".join(parts), w, h, title)


# ---------------- V4 环比涨跌（分歧条形） ----------------

def diverging(data: list[dict], title: str, w: int = 680) -> str:
    """data: [{name, value}] 正负百分比，已排序"""
    if not data:
        return _empty(title)
    row_h, pad_t = 24, 18
    h = pad_t + row_h * len(data) + 14
    mid = w / 2
    label_w = 118
    max_abs = max(abs(d["value"]) for d in data) or 1
    half = (w - label_w * 2) / 2

    parts = [f'<line x1="{mid}" y1="{pad_t - 6}" x2="{mid}" y2="{h - 8}" stroke="{LINE}" stroke-width="1"/>']
    parts.append(f'<text x="{mid}" y="11" text-anchor="middle" font-size="10" fill="{MUTED}">环比变化</text>')
    for i, d in enumerate(data):
        y = pad_t + i * row_h
        v = d["value"]
        bw = half * abs(v) / max_abs
        is_up = v >= 0
        color = "#2E7D5B" if is_up else MUTED
        x = mid if is_up else mid - bw
        arrow = "↑" if is_up else "↓"
        tip = f'{d["name"]}：{v:+.1f}%'
        parts.append(
            f'<g><title>{_esc(tip)}</title>'
            f'<text x="{mid - 8 if is_up else mid + 8}" y="{y + 15}" '
            f'text-anchor="{"end" if is_up else "start"}" font-size="11.5" fill="{TEXT}">{_esc(d["name"])}</text>'
            f'<rect x="{x:.1f}" y="{y + 5}" width="{bw:.1f}" height="12" rx="2" fill="{color}"/>'
            f'<text x="{(mid + bw + 6) if is_up else (mid - bw - 6):.1f}" y="{y + 15}" '
            f'text-anchor="{"start" if is_up else "end"}" font-size="10.5" fill="{color}">{arrow}{abs(v):.1f}%</text>'
            f"</g>"
        )
    return _wrap("".join(parts), w, h, title)


# ---------------- V5/V7 堆叠条 ----------------

STACK_COLORS = [INK, INK_3, INK_4, INK_5, "#EDF1F5"]


def stacked(parts_data: list[dict], title: str, w: int = 680,
            show_legend: bool = True) -> str:
    """parts_data: [{name, value}]，渲染成一条水平堆叠 + 图例"""
    total = sum(p["value"] for p in parts_data) or 1
    bar_h, pad_t = 26, 8
    h = pad_t + bar_h + (46 if show_legend else 8)
    x = 0.0
    seg = []
    for i, p in enumerate(parts_data):
        width = w * p["value"] / total
        color = STACK_COLORS[i % len(STACK_COLORS)]
        pct = p["value"] / total * 100
        seg.append(
            f'<g><title>{_esc(p["name"])}：{p["value"]:g} 条（{pct:.0f}%）</title>'
            f'<rect x="{x:.1f}" y="{pad_t}" width="{max(0, width - 1):.1f}" height="{bar_h}" '
            f'fill="{color}"/>'
            + (f'<text x="{x + width / 2:.1f}" y="{pad_t + bar_h / 2 + 4:.1f}" text-anchor="middle" '
               f'font-size="11" fill="{"#FFFFFF" if i < 2 else TEXT}">{pct:.0f}%</text>'
               if width > 34 else "")
            + "</g>"
        )
        x += width

    legend = ""
    if show_legend:
        ly = pad_t + bar_h + 22
        lx = 0
        for i, p in enumerate(parts_data):
            color = STACK_COLORS[i % len(STACK_COLORS)]
            label = f'{p["name"]} {p["value"]:g}'
            legend += (f'<rect x="{lx}" y="{ly - 8}" width="9" height="9" rx="1.5" fill="{color}"/>'
                       f'<text x="{lx + 14}" y="{ly}" font-size="11" fill="{TEXT}">{_esc(label)}</text>')
            lx += 22 + len(label) * 8
    return _wrap("".join(seg) + legend, w, h, title)


# ---------------- V6 环形 ----------------

def donut(parts_data: list[dict], title: str, size: int = 240) -> str:
    import math
    total = sum(p["value"] for p in parts_data) or 1
    cx = cy = size / 2
    r_out, r_in = size / 2 - 6, size / 2 - 34
    angle = -math.pi / 2
    parts = []
    for i, p in enumerate(parts_data):
        frac = p["value"] / total
        end = angle + frac * 2 * math.pi
        large = 1 if frac > 0.5 else 0
        x1, y1 = cx + r_out * math.cos(angle), cy + r_out * math.sin(angle)
        x2, y2 = cx + r_out * math.cos(end), cy + r_out * math.sin(end)
        x3, y3 = cx + r_in * math.cos(end), cy + r_in * math.sin(end)
        x4, y4 = cx + r_in * math.cos(angle), cy + r_in * math.sin(angle)
        color = STACK_COLORS[i % len(STACK_COLORS)]
        parts.append(
            f'<g><title>{_esc(p["name"])}：{p["value"]:g} 条</title>'
            f'<path d="M{x1:.1f},{y1:.1f} A{r_out},{r_out} 0 {large} 1 {x2:.1f},{y2:.1f} '
            f'L{x3:.1f},{y3:.1f} A{r_in},{r_in} 0 {large} 0 {x4:.1f},{y4:.1f} Z" '
            f'fill="{color}" stroke="#FFFFFF" stroke-width="1.5"/></g>'
        )
        angle = end
    parts.append(
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-size="19" font-weight="600" fill="{INK}">'
        f'{total:g}</text>'
        f'<text x="{cx}" y="{cy + 15}" text-anchor="middle" font-size="10.5" fill="{MUTED}">总条目</text>'
    )
    return _wrap("".join(parts), size, size, title)


def _empty(title: str) -> str:
    return _wrap(
        f'<rect x="0" y="0" width="680" height="80" fill="#F7F9FB" rx="4"/>'
        f'<text x="340" y="45" text-anchor="middle" font-size="12" fill="{MUTED}">暂无数据</text>',
        680, 80, title,
    )
