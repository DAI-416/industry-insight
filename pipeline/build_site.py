"""P9 站点构建：生成静态页面与图表。

页面：首页 / 25 个赛道详情 / 数据看板 / 检索
"""
from __future__ import annotations

from collections import Counter, defaultdict
from html import escape

from . import charts, site_assets, util

MARKET_NAME = {"M-A": "A股", "M-HK": "港股", "M-CN": "中概", "M-GL": "全球"}
LEVEL_NAME = {"critical": "关键", "important": "重要", "normal": "一般", "low": "低"}
DOMAIN_ORDER = ["investment", "tech", "macro"]

ICON_ART = {
    "TEC-AI": ["..####..", ".#....#.", "#..##..#", "#.####.#", "#..##..#",
               ".#....#.", "..####..", "........"],
    "TEC-ROBO": ["..####..", ".######.", ".#.##.#.", ".#.##.#.", ".######.",
                 ".#....#.", ".#....#.", "..#..#.."],
    "TEC-SEMI": [".#....#.", "########", "#.####.#", "#.#..#.#", "#.#..#.#",
                 "#.####.#", "########", ".#....#."],
    "default": ["........", "......#.", "..#...#.", "..#.#.#.", "#.#.#.#.",
                "#.#.#.#.", "#.#.#.#.", "########"],
}


def pixel_icon(track_id: str, color: str = "#fee761") -> str:
    """8x8 字符画转 SVG，最近邻放大到 32x32。"""
    art = ICON_ART.get(track_id) or ICON_ART["default"]
    rects = "".join(
        f'<rect x="{x}" y="{y}" width="1" height="1" fill="{color}"/>'
        for y, row in enumerate(art)
        for x, ch in enumerate(row) if ch == "#"
    )
    return f'<svg viewBox="0 0 8 8" shape-rendering="crispEdges">{rects}</svg>'


FOOTER = """
<footer>
  <div class="wrap">
    <div class="save-slot">
      <span class="slot-no">SAVE SLOT 01</span>
      <b>__WEEK__</b>
      <span>最后存档 __TS__</span>
    </div><br>
    <b class="hl">口径</b>　赛道活跃度 = Σ(事实类重要度分) × 0.6 + 条目数 × 4；重要度满分 100，核心关注赛道 ×1.15。<br>
    <b class="hl">重要</b>　活跃度反映<b>报道密集度</b>，不等同于行业景气度。媒体密集报道可能仅因单一热点事件，
    不代表行业基本面好转。本页仅聚合公开资讯摘要并保留原文链接，不构成投资建议。<br>
    <b class="hl">来源</b>　公开 RSS 源；摘要由模型生成或取原文首句，每条均可回溯原文。
  </div>
</footer>
"""


def _e(s) -> str:
    return escape(str(s or ""), quote=True)


def _ts() -> str:
    return f"{util.now():%Y-%m-%d %H:%M}"


# ---------------- 页面骨架 ----------------

def page(title: str, active: str, body: str, root: str = ".", week_label: str = "--") -> str:
    nav = [("index.html", "首页", "home"), ("models.html", "大模型", "models"),
           ("analytics.html", "数据看板", "analytics"), ("search.html", "检索", "search")]
    nav_html = "".join(
        f'<a href="{root}/{href}" class="{"on" if key == active else ""}">{label}</a>'
        for href, label, key in nav
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="投资 · 科技 · 宏观 三域行业动态周报，聚焦 AI、人形机器人、脑机接口、半导体">
<link rel="stylesheet" href="{root}/assets/style.css">
</head>
<body>
<header class="top"><div class="wrap top-in">
  <a class="brand" href="{root}/index.html">行业洞察<small>三域周报</small></a>
  <nav class="nav">{nav_html}</nav>
  <div class="top-right"></div>
</div></header>
{body}
{FOOTER.replace("__WEEK__", week_label).replace("__TS__", _ts())}
<script src="{root}/assets/app.js"></script>
</body></html>"""


def topbar_extra(week: str, updated: str, root: str = ".") -> str:
    return f"""<div class="market-filter">
  <button data-m="ALL" class="on">ALL</button>
  <button data-m="M-A">A股</button>
  <button data-m="M-HK">港股</button>
  <button data-m="M-CN">中概</button>
  <button data-m="M-GL">全球</button>
</div><span>WEEK {_e(week.replace("-", " "))}</span><span>UPD {_e(updated)}</span>"""


# ---------------- 条目渲染 ----------------

def item_html(e: dict, track_map: dict, show_track: bool = True) -> str:
    lvl = e.get("importance_level", "low")
    score = e.get("importance_score", 0)
    score_cls = "critical" if lvl == "critical" else "important" if lvl == "important" else ""
    score_txt = "—" if e.get("content_type") == "opinion" else str(score)
    track = track_map.get(e.get("track_id", ""), {})
    market = MARKET_NAME.get(e.get("market_primary", ""), "全球")

    badges = []
    if e.get("pinned"):
        badges.append('<span class="pin">★ 置顶</span>')
    if show_track and track:
        badges.append(f'<span class="badge">{_e(track["name"])}</span>')
    if e.get("content_type") == "opinion":
        badges.append('<span class="badge opinion">观点</span>')
    conf = e.get("classify_confidence")
    if conf is not None and conf < 0.7:
        # 按信源推断是「有依据但精度有限」，用中性徽标；纯规则低分才标红
        if e.get("classify_method") == "rules:source_hint":
            badges.append('<span class="badge">按信源归类</span>')
        else:
            badges.append('<span class="badge lowconf">低置信归类</span>')
    if e.get("is_manual"):
        badges.append('<span class="badge">人工补录</span>')

    return f"""<div class="item" data-market="{_e(_market_id(e))}">
  <div class="score {score_cls}">{score_txt}<small>{_e(LEVEL_NAME.get(lvl, ""))}</small></div>
  <div>
    <div class="i-title" onclick="window.__openDrawer('{_e(e.get('id',''))}')">{_e(e.get('title',''))}</div>
    <div class="i-sum">{_e(e.get('ai_summary',''))}</div>
    <div class="i-meta">{''.join(badges)}<span>{_e(e.get('source_name',''))}</span>
      <span>{_e(util.truncate(e.get('published_at','')[:10], 10))}</span>
      <span>{_e(market)}</span></div>
  </div>
</div>"""


def _market_id(e: dict) -> str:
    return e.get("market_primary", "")


def drawer_inner(e: dict, track_map: dict) -> str:
    """抽屉内部 HTML（不含外层容器，供页面内嵌或前端按需渲染）"""
    track = track_map.get(e.get("track_id", ""), {})
    sources = e.get("sources") or [{
        "name": e.get("source_name", ""), "url": e.get("url", ""),
        "level": e.get("source_level", ""), "title": e.get("title", ""),
    }]
    src_rows = "".join(
        f'<div class="src">[{_e(s.get("level",""))}] {_e(s.get("name",""))}　'
        f'<a href="{_e(s.get("url",""))}" target="_blank" rel="noopener noreferrer">查看原文 ↗</a></div>'
        for s in sources[:6]
    )
    audit = e.get("audit") or {}
    if e.get("is_manual"):
        audit_txt = "人工补录，摘要由人工撰写"
    elif audit.get("pass"):
        method = {"llm": "模型生成", "first_sentence": "原文首句", "fallback": "安全降级"}.get(
            e.get("summary_method", ""), "原文首句")
        audit_txt = f'<span class="ok">✓ 已通过校验</span>（{method}，数字可在原文定位）'
    else:
        audit_txt = f'<span class="warn">⚠ 校验未通过，已降级处理</span>（{", ".join(audit.get("issues", []))}）'

    meta = [MARKET_NAME.get(e.get("market_primary", ""), "全球")]
    if track:
        meta.append(track["name"])
    if e.get("event_type"):
        meta.append(e["event_type"])
    if e.get("content_type") == "fact":
        meta.append(f"重要度 {e.get('importance_score', 0)}")
    meta.append(util.truncate(e.get("published_at", "")[:16].replace("T", " "), 16))

    return f"""<h3>{_e(e.get('title',''))}</h3>
  <div class="meta">{''.join(f"<span>{_e(m)}</span>" for m in meta)}</div>
  <div class="sum" data-text="{_e(e.get('ai_summary',''))}">{_e(e.get('ai_summary',''))}</div>
  <h4>原文来源（{e.get('source_count', 1)} 个）</h4>
  {src_rows}
  <div class="audit">{audit_txt}</div>
"""


def drawer_html(e: dict, track_map: dict) -> str:
    return (f'<div id="d-{_e(e.get("id", ""))}" style="display:none">'
            f'{drawer_inner(e, track_map)}</div>')


# ---------------- 首页 ----------------

def build_index(events: list[dict], stats: dict, tax: dict, week: str) -> str:
    track_map = {t["id"]: t for t in tax["tracks"]}
    wk = stats["weekly"].get(week, {})
    track_act = {t["track_id"]: t for t in wk.get("track_activity", [])}
    prev_week = util.prev_week(week)
    prev_act = {t["track_id"]: t for t in stats["weekly"].get(prev_week, {}).get("track_activity", [])}

    week_events = [e for e in events if e.get("week_key") == week and e.get("status") == "published"]
    notice = ""
    if not week_events:
        # 本周尚无数据时回退到上一周
        week = prev_week
        week_events = [e for e in events if e.get("week_key") == week and e.get("status") == "published"]
        notice = f'<div class="empty" style="margin-bottom:18px"><b>本周数据积累中</b>以下展示上周（{_e(week)}）内容</div>'

    facts = [e for e in week_events if e.get("content_type") == "fact"]
    opinions = [e for e in week_events if e.get("content_type") == "opinion"]

    def trend_html(tid: str) -> str:
        cur = track_act.get(tid, {}).get("score", 0)
        prv = prev_act.get(tid, {}).get("score", 0)
        if prv <= 0:
            return '<span class="trend-down">—</span>'
        delta = (cur - prv) / prv * 100
        # 基数极小时百分比会失真（1 条→22 条 = +2100%），超过 3 倍用倍数表达
        if delta > 15:
            txt = f"{cur / prv:.1f} 倍" if delta >= 300 else f"{delta:.0f}%"
            return f'<span class="trend-up">↑ {txt}</span>'
        if delta < -15:
            return f'<span class="trend-down">↓ {abs(delta):.0f}%</span>'
        return '<span class="trend-down">持平</span>'

    def top_points(tid: str, n: int) -> list[dict]:
        rows = [e for e in facts if e.get("track_id") == tid]
        rows.sort(key=lambda x: (-int(x.get("pinned", False)), -x.get("importance_score", 0)))
        return rows[:n]

    # --- 核心关注 ---
    focus_cards = []
    for t in [x for x in tax["tracks"] if x.get("is_focus")]:
        pts = top_points(t["id"], 2)
        act = track_act.get(t["id"], {})
        li = "".join(
            f'<li onclick="window.__openDrawer(\'{_e(p.get("id",""))}\')" style="cursor:pointer">'
            f'{_e(util.truncate(p.get("title",""), 42))}</li>' for p in pts
        ) or '<li class="empty">本周无重大动态</li>'
        focus_cards.append(f"""<div class="focus-card" data-market="{_e(_dominant_market(pts))}">
  <span class="tag">CORE</span>
  <div class="fc-head">
    <div class="fc-portrait">{pixel_icon(t["id"])}</div>
    <div>
      <div class="fc-name"><a href="track/{_e(t['id'])}.html">{_e(t['name'])}</a></div>
      <div class="fc-meta"><span>本周 {act.get('count', 0)} 条</span>{trend_html(t['id'])}</div>
    </div>
  </div>
  <ul class="fc-points">{li}</ul>
</div>""")

    # --- 三域 ---
    domains_html = []
    for did in DOMAIN_ORDER:
        dom = next((d for d in tax["domains"] if d["id"] == did), None)
        if not dom:
            continue
        rows = []
        for t in [x for x in tax["tracks"] if x["domain"] == did]:
            pts = top_points(t["id"], 1)
            act = track_act.get(t["id"], {})
            top_txt = (f'<span style="cursor:pointer" onclick="window.__openDrawer(\'{_e(pts[0].get("id",""))}\')">'
                       f'{_e(util.truncate(pts[0].get("title",""), 60))}</span>') if pts \
                else '<span style="color:var(--ink5)">本周无动态</span>'
            dot = '<span class="focus-dot"></span>' if t.get("is_focus") else ""
            rows.append(f"""<div class="track-row" data-market="{_e(_dominant_market(pts))}">
  <div class="tr-name">{dot}<a href="track/{_e(t['id'])}.html">{_e(t['name'])}</a></div>
  <div class="tr-top">{top_txt}</div>
  <div class="tr-stat"><b>{act.get('count', 0)}</b>{trend_html(t['id'])}</div>
</div>""")
        domains_html.append(f"""<div class="domain">
  <div class="domain-head"><h3>{_e(dom['name'])}</h3><span>{_e(dom['desc'])}</span></div>
  {''.join(rows)}
</div>""")

    # --- 关键信号 ---
    signals = sorted([e for e in facts if e.get("importance_level") == "critical"],
                     key=lambda x: (-int(x.get("pinned", False)), -x.get("importance_score", 0)))[:10]
    signals_html = "".join(item_html(e, track_map) for e in signals) or \
        '<div class="empty"><b>本周暂无关键信号</b>重要度 ≥75 的事件会出现在这里</div>'

    # --- 观点 ---
    opinions_sorted = sorted(opinions, key=lambda x: x.get("published_at", ""), reverse=True)[:5]
    opinions_html = "".join(item_html(e, track_map) for e in opinions_sorted) or \
        '<div class="empty"><b>本周暂无观点内容</b>研报与评论类条目会归入这里</div>'

    # --- 实时流 ---
    live = sorted(week_events, key=lambda x: x.get("published_at", ""), reverse=True)[:60]
    live_html = "".join(item_html(e, track_map) for e in live) or \
        '<div class="empty"><b>本周尚无条目</b>采集任务每 3-6 小时运行一次</div>'

    drawers = "".join(drawer_html(e, track_map) for e in live)

    body = f"""
<div class="wrap">
  {notice}
  <div class="section">
    <div class="section-head"><h2>核心关注</h2>
      <span class="note">AI · 人形机器人 · 脑机接口 · 半导体</span></div>
    <div class="focus-grid">{''.join(focus_cards)}</div>
  </div>

  <div class="section">
    <div class="section-head"><h2>三域动态</h2>
      <span class="note">投资 → 钱往哪去 · 科技 → 技术进展 · 宏观 → 政策与数据</span></div>
    {''.join(domains_html)}
  </div>

  <div class="section">
    <div class="section-head"><h2>本周关键信号</h2>
      <span class="note">重要度 ≥ 75，最多 10 条</span></div>
    {signals_html}
  </div>

  <div class="section">
    <div class="section-head"><h2>观点与解读</h2>
      <span class="note">不参与活跃度计算</span></div>
    {opinions_html}
  </div>

  <div class="section">
    <div class="section-head"><h2>本周实时流</h2>
      <span class="note">本周至今全部条目，按时间倒序</span></div>
    {live_html}
  </div>
</div>
<div class="drawer-mask"></div><aside class="drawer"></aside>
{drawers}
"""
    html = page(f"行业洞察 · {week}", "home", body, week_label=week)
    # 顶栏右侧注入市场筛选
    html = html.replace('<div class="top-right"></div>',
                        f'<div class="top-right">{topbar_extra(week, _ts())}</div>')
    return html


def _dominant_market(items: list[dict]) -> str:
    if not items:
        return ""
    return Counter(i.get("market_primary", "M-GL") for i in items).most_common(1)[0][0]


# ---------------- 赛道详情 ----------------

def build_track(t: dict, events: list[dict], stats: dict, tax: dict, week: str) -> str:
    track_map = {x["id"]: x for x in tax["tracks"]}
    wk = stats["weekly"].get(week, {})
    act = next((x for x in wk.get("track_activity", []) if x["track_id"] == t["id"]), {})

    rows = sorted([e for e in events if e.get("track_id") == t["id"] and e.get("week_key") == week
                   and e.get("status") == "published"],
                  key=lambda x: (-int(x.get("pinned", False)), -x.get("importance_score", 0)))
    facts = [e for e in rows if e.get("content_type") == "fact"]
    ops = [e for e in rows if e.get("content_type") == "opinion"]

    # 近 8 周迷你折线
    weeks8 = util.last_n_weeks(week, 8)
    series_vals = []
    for w in weeks8:
        d = stats["weekly"].get(w, {})
        a = next((x for x in d.get("track_activity", []) if x["track_id"] == t["id"]), None)
        series_vals.append(a["score"] if a else 0)
    mini = charts.multiline(
        [{"name": t["name"], "values": series_vals}], weeks8,
        f"{t['name']} 近 8 周活跃度", w=680, h=180)

    market_dist = Counter(e.get("market_primary", "M-GL") for e in rows)
    stack = charts.segbar(
        [{"name": MARKET_NAME.get(k, k), "value": v} for k, v in market_dist.most_common()],
        f"{t['name']} 本周市场分布", w=680)

    facts_html = "".join(item_html(e, track_map, show_track=False) for e in facts) or \
        '<div class="empty"><b>本周该赛道无事实类条目</b></div>'
    ops_html = "".join(item_html(e, track_map, show_track=False) for e in ops) or \
        '<div class="empty"><b>本周该赛道无观点内容</b></div>'

    body = f"""
<div class="wrap">
  <div class="section">
    <div class="section-head">
      <h2>{_e(t['name'])}</h2>
      <span class="note">{_e(t.get('scope',''))}　·　本周 {act.get('count',0)} 条事实 / {act.get('opinion_count',0)} 条观点　·　活跃度 {act.get('score',0):g}</span>
    </div>
    <div class="chart-card"><h3>近 8 周活跃度走势</h3>
      <div class="caliber">口径：Σ重要度分 × 0.6 + 条目数 × 4</div>{mini}</div>
    <div class="chart-card"><h3>本周市场分布</h3>
      <div class="caliber">按条目主市场统计</div>{stack}</div>
  </div>

  <div class="section">
    <div class="section-head"><h2>本周事实动态</h2><span class="note">按重要度排序</span></div>
    {facts_html}
  </div>

  <div class="section">
    <div class="section-head"><h2>观点与解读</h2><span class="note">不参与活跃度计算</span></div>
    {ops_html}
  </div>
</div>
<div class="drawer-mask"></div><aside class="drawer"></aside>
{''.join(drawer_html(e, track_map) for e in rows)}
"""
    html = page(f"{t['name']} · 行业洞察", "home", body, root="..", week_label=week)
    return html.replace('<div class="top-right"></div>',
                        f'<div class="top-right">{topbar_extra(week, _ts(), root="..")}</div>')


# ---------------- 数据看板 ----------------

def build_analytics(events: list[dict], stats: dict, tax: dict, week: str) -> str:
    track_map = {x["id"]: x for x in tax["tracks"]}
    wk = stats["weekly"].get(week, {})
    prev = stats["weekly"].get(util.prev_week(week), {})
    act = wk.get("track_activity", [])
    prev_map = {x["track_id"]: x for x in prev.get("track_activity", [])}
    focus_ids = {x["id"] for x in tax["tracks"] if x.get("is_focus")}

    # 只保留「有数据」的周次：数据积累期空白列没有信息量，反而稀释对比度
    all_weeks = util.last_n_weeks(week, 12)
    weeks_data = [w for w in all_weeks if stats["weekly"].get(w, {}).get("total", 0) > 0] or [week]

    summaries = stats["summaries"].get(week, {}).get("items", [])
    sum_html = "".join(
        f'<li class="sum-item"><b>{_e(s["id"])}</b><span>{_e(s["text"])}</span></li>'
        for s in summaries) or '<li class="sum-item"><b>--</b><span>本周数据不足</span></li>'

    # V9 · 本周热词（词云）
    hot = wk.get("top_entities", [])
    cloud = charts.wordcloud(hot, "本周热词", w=680, h=330)

    # V1 · 活跃度排行
    v1_data = [{"name": x["name"], "value": x["score"], "key": x["track_id"],
                "sub": f"{x['count']} 条"} for x in act
               if x["count"] > 0 and x["track_id"] != "OTHER-1"][:14]
    v1 = charts.hbar(v1_data, "赛道活跃度排行", highlight=focus_ids)

    # V3 · 热力矩阵（红=火热 绿=冷）
    order = [x["track_id"] for x in act
             if x["count"] > 0 and x["track_id"] != "OTHER-1"][:12] \
        or [x["id"] for x in tax["tracks"] if x["id"] != "OTHER-1"][:8]
    rows = [{"name": track_map[tid]["name"], "is_focus": tid in focus_ids} for tid in order]
    matrix = []
    for tid in order:
        line = []
        for w in weeks_data:
            a = next((x for x in stats["weekly"].get(w, {}).get("track_activity", [])
                      if x["track_id"] == tid), None)
            line.append(a["score"] if (a and a["count"] > 0) else None)
        matrix.append(line)
    v3 = charts.heatmap(rows, weeks_data, matrix, "赛道 × 周 活跃度热力矩阵", w=680)

    # V4 · 环比
    deltas = []
    for x in act:
        pv = prev_map.get(x["track_id"])
        if not pv or pv["score"] <= 0 or x["count"] < 3:
            continue
        deltas.append({"name": x["name"],
                       "value": round((x["score"] - pv["score"]) / pv["score"] * 100, 1)})
    deltas.sort(key=lambda d: -abs(d["value"]))
    v4 = charts.diverging(deltas[:10], "活跃度环比变化")

    # V8 · 信源贡献
    v8 = charts.hbar([{"name": s["name"], "value": s["count"]} for s in stats["sources"]],
                     "信源贡献 Top 10", unit=" 条", label_w=112)

    body = f"""
<div class="wrap">
  <div class="section">
    <div class="section-head"><h2>本周数据摘要</h2>
      <span class="note">代码统计 · 非模型撰写 · {_e(week)}</span></div>
    <ul class="sum-list">{sum_html}</ul>
  </div>

  <div class="section">
    <div class="section-head"><h2>本周热词</h2>
      <span class="note">按「被多少条新闻提及」排序 · 字号即热度</span></div>
    <div class="chart-card">
      <div class="caliber">口径：统计标题与摘要中出现的赛道术语与专名，同一篇内多次出现只计 1 次</div>
      {cloud}
    </div>
  </div>

  <div class="section">
    <div class="section-head"><h2>本周快照</h2><span class="note">V1 · 赛道活跃度</span></div>
    <div class="chart-card">
      <div class="caliber">口径：Σ事实类重要度分 × 0.6 + 条目数 × 4；黄色为核心关注赛道</div>
      {v1}
    </div>
  </div>

  <div class="section">
    <div class="section-head"><h2>时序趋势</h2>
      <span class="note">仅显示有数据的 {len(weeks_data)} 周</span></div>
    <div class="chart-card"><h3>V3 · 赛道 × 周 活跃度热力矩阵</h3>
      <div class="caliber">红=火热 绿=冷 黄橙=中间档；<b>空心格=该周无条目</b></div>{v3}</div>
    <div class="chart-card"><h3>V4 · 活跃度环比</h3>
      <div class="caliber">红升绿降；仅统计本周 ≥3 条且上周有数据的赛道</div>{v4}</div>
  </div>

  <div class="section">
    <div class="section-head"><h2>结构与来源</h2><span class="note">V8 · 信源贡献</span></div>
    <div class="chart-card">
      <div class="caliber">近 4 周各源被采用条目数；骤降说明采集可能失效</div>{v8}
    </div>
  </div>
</div>
"""
    html = page("数据看板 · 行业洞察", "analytics", body, week_label=week)
    return html.replace('<div class="top-right"></div>',
                        f'<div class="top-right">{topbar_extra(week, _ts())}</div>')


# ---------------- 检索页 ----------------

SEARCH_TPL = """
<div class="wrap">
  <div class="section">
    <div class="section-head"><h2>检索</h2>
      <span class="note">全站 __COUNT__ 条已发布条目</span></div>
    <div class="search-box"><input id="q" type="search" placeholder="输入关键词，如「人形机器人」「光模块」「降准」" autocomplete="off"></div>
    <div class="filters">
      <select id="f-track"><option value="">全部赛道</option>__TRACK_OPTS__</select>
      <select id="f-market"><option value="">全部市场</option>__MARKET_OPTS__</select>
      <select id="f-type"><option value="">全部类型</option><option value="fact">事实</option><option value="opinion">观点</option></select>
      <select id="f-level"><option value="">全部重要度</option><option value="critical">关键信号</option><option value="important">重要</option><option value="normal">一般</option><option value="low">低优先级</option></select>
    </div>
    <div class="result-count" id="rcount"></div>
    <div id="results"></div>
  </div>
</div>
<div class="drawer-mask"></div><aside class="drawer"></aside>
<script>window.__DATA = __DATA__;</script>
"""


def build_search(events: list[dict], tax: dict, week: str) -> str:
    import json
    track_map = {x["id"]: x for x in tax["tracks"]}
    rows = [e for e in events if e.get("status") == "published"]
    rows.sort(key=lambda x: x.get("published_at", ""), reverse=True)

    data = [{
        "i": e.get("id", ""),
        "t": e.get("title", ""),
        "s": e.get("ai_summary", ""),
        "k": e.get("track_id", ""),
        "m": MARKET_NAME.get(e.get("market_primary", ""), "全球"),
        "y": e.get("content_type", "fact"),
        "l": e.get("importance_level", "low"),
        "v": e.get("importance_score", 0),
        "w": str(e.get("week_key", ""))[-2:],
        "n": e.get("source_name", ""),
        "o": str(e.get("published_at", ""))[:10],
        "c": e.get("classify_confidence", 1),
        "h": drawer_inner(e, track_map),
    } for e in rows]

    track_opts = "".join(f'<option value="{_e(t["id"])}">{_e(t["name"])}</option>' for t in tax["tracks"])
    market_opts = "".join(f'<option value="{k}">{v}</option>' for k, v in MARKET_NAME.items())

    inner = (SEARCH_TPL
             .replace("__COUNT__", str(len(rows)))
             .replace("__TRACK_OPTS__", track_opts)
             .replace("__MARKET_OPTS__", market_opts)
             .replace("__DATA__", json.dumps(data, ensure_ascii=False)))

    html = page("检索 · 行业洞察", "search", inner, week_label=week)
    return html.replace('<div class="top-right"></div>',
                        f'<div class="top-right">{topbar_extra(week, _ts())}</div>')


# ---------------- 大模型专栏 ----------------

def load_models_cfg() -> dict:
    cfp = util.CONFIG_DIR / "models.yml"
    if not cfp.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(cfp.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _vendor_hits(items: list[dict], models_cfg: dict) -> list[dict]:
    """统计本周各大模型厂商被提及的条数。"""
    models = models_cfg.get("models", [])
    by_vendor: dict[str, list[dict]] = {}
    for m in models:
        by_vendor.setdefault(m["vendor"], []).append(m)

    out = []
    for vendor, ms in by_vendor.items():
        needles = {vendor.split()[0]} | {m["name"] for m in ms}
        # 去掉厂商中文名里的括号说明
        needles |= {w for w in vendor.replace("（", " ").replace("）", " ").split() if len(w) > 1}
        hits = []
        for it in items:
            text = f"{it.get('title', '')} {it.get('ai_summary', '')}"
            if any(n and n in text for n in needles):
                hits.append(it)
        best = max(ms, key=lambda x: x["index"])
        out.append({
            "vendor": vendor,
            "count": len(hits),
            "top_model": best["name"],
            "top_index": best["index"],
            "latest": hits[0]["title"] if hits else "",
            "latest_id": hits[0].get("id", "") if hits else "",
        })
    out.sort(key=lambda x: (-x["count"], -x["top_index"]))
    return out


def build_models(events: list[dict], stats: dict, tax: dict, week: str) -> str:
    track_map = {x["id"]: x for x in tax["tracks"]}
    cfg = load_models_cfg()
    models = cfg.get("models", [])
    as_of = cfg.get("as_of", "—")
    source = cfg.get("source", "")
    source_url = cfg.get("source_url", "")

    week_items = [e for e in events if e.get("week_key") == week and e.get("status") == "published"]
    llm_items = sorted([e for e in week_items if e.get("track_id") == "LLM"],
                       key=lambda x: (-int(x.get("pinned", False)), -x.get("importance_score", 0)))

    # ---- 跑分图：三个维度，前端切换 ----
    if models:
        def vrows(rows: list[dict], key: str, transform=lambda v: v) -> list[dict]:
            return [{"name": m["name"], "value": transform(m[key] if key in m else 0),
                     "vendor": m["vendor"]} for m in rows]

        by_index = sorted(models, key=lambda m: -m["index"])[:12]
        chart_index = charts.vbar(vrows(by_index, "index"), "综合智能指数", value_fmt="{:.1f}")

        by_ctx = sorted(models, key=lambda m: -(m.get("context_k") or 0))[:12]
        chart_ctx = charts.vbar(vrows(by_ctx, "context_k"), "上下文窗口", unit="k")

        # 先按价格排序再截断，否则会漏掉价格最低的型号
        by_price = sorted([m for m in models if m.get("price_out")],
                          key=lambda m: m["price_out"])[:12]
        chart_price = charts.vbar(vrows(by_price, "price_out"),
                                  "输出价格", unit=" $/M", value_fmt="{:.2f}")

        charts_html = f"""
    <div class="chart-card">
      <h3>跑分排行</h3>
      <div class="caliber">
        数据源：<a href="{_e(source_url)}" target="_blank" rel="noopener">{_e(source)}</a>　
        截至 {_e(as_of)}　·　{_e(cfg.get("note", ""))}
      </div>
      <div class="tab-row">
        <button class="tab-btn on" data-tab="idx">综合指数</button>
        <button class="tab-btn" data-tab="ctx">上下文</button>
        <button class="tab-btn" data-tab="price">输出价格</button>
      </div>
      <div data-panel="idx">{chart_index}</div>
      <div data-panel="ctx" style="display:none">{chart_ctx}</div>
      <div data-panel="price" style="display:none">{chart_price}</div>
    </div>"""
    else:
        charts_html = """
    <div class="chart-card">
      <h3>跑分排行</h3>
      <div class="empty"><b>暂无跑分数据</b>
        运行 <code>python3 tools/update_benchmarks.py</code> 抓取，或手工填写 config/models.yml</div>
    </div>"""

    # ---- 厂商动态 ----
    vendors = _vendor_hits(week_items, cfg) if models else []
    vendor_cards = "".join(
        f"""<div class="vendor-card" data-market="">
  <div class="vc-head"><span class="vc-name">{_e(v['vendor'])}</span>
    <span class="vc-count">{v['count']} 条</span></div>
  <div class="vc-bar"><i style="width:{min(100, v['count'] / max(1, vendors[0]['count']) * 100):.0f}%"></i></div>
  <div class="vc-meta">旗舰 {_e(v['top_model'])} · {v['top_index']}</div>
  <div class="vc-latest" onclick="window.__openDrawer('{_e(v['latest_id'])}')">{_e(util.truncate(v['latest'], 46)) or '本周无相关资讯'}</div>
</div>"""
        for v in vendors[:12]
    ) or '<div class="empty"><b>本周无模型厂商动态</b></div>'

    # ---- 资讯流 ----
    stream = "".join(item_html(e, track_map, show_track=False) for e in llm_items[:40]) or \
        '<div class="empty"><b>本周暂无大模型资讯</b>检查 config/sources.yml 中 LLM 相关信源是否可用</div>'

    body = f"""
<div class="wrap">
  <div class="section">
    <div class="section-head"><h2>大模型专栏</h2>
      <span class="note">版本迭代 · 能力评测 · 厂商动态　{_e(week)}</span></div>
    {charts_html}
  </div>

  <div class="section">
    <div class="section-head"><h2>厂商动态</h2>
      <span class="note">按本周被提及条数排序</span></div>
    <div class="vendor-grid">{vendor_cards}</div>
  </div>

  <div class="section">
    <div class="section-head"><h2>本周大模型资讯</h2>
      <span class="note">共 {len(llm_items)} 条 · 关于模型本身而非应用</span></div>
    {stream}
  </div>
</div>
<div class="drawer-mask"></div><aside class="drawer"></aside>
{''.join(drawer_html(e, track_map) for e in llm_items[:40])}
"""
    html = page("大模型 · 行业洞察", "models", body, week_label=week)
    return html.replace('<div class="top-right"></div>',
                        f'<div class="top-right">{topbar_extra(week, _ts())}</div>')


# ---------------- 资产与入口 ----------------

def write_assets(site_dir) -> None:
    (site_dir / "assets").mkdir(parents=True, exist_ok=True)
    (site_dir / "assets" / "style.css").write_text(site_assets.CSS, encoding="utf-8")
    (site_dir / "assets" / "app.js").write_text(site_assets.JS, encoding="utf-8")


def run(events: list[dict], stats: dict, weeks: list[str], current_week: str) -> None:
    tax = util.load_taxonomy()
    site = util.SITE_DIR
    track_dir = site / "track"
    # 清掉历史赛道页：taxonomy 删过赛道后，旧 html 会残留在目录里
    if track_dir.exists():
        for old in track_dir.glob("*.html"):
            old.unlink()
    track_dir.mkdir(parents=True, exist_ok=True)
    write_assets(site)

    published_weeks = sorted({e.get("week_key") for e in events
                              if e.get("week_key") and e.get("status") == "published"})
    display_week = published_weeks[-1] if published_weeks else current_week

    (site / "index.html").write_text(build_index(events, stats, tax, display_week), encoding="utf-8")
    (site / "analytics.html").write_text(build_analytics(events, stats, tax, display_week), encoding="utf-8")
    (site / "search.html").write_text(build_search(events, tax, display_week), encoding="utf-8")
    (site / "models.html").write_text(build_models(events, stats, tax, display_week), encoding="utf-8")

    for t in tax["tracks"]:
        (track_dir / f"{t['id']}.html").write_text(
            build_track(t, events, stats, tax, display_week), encoding="utf-8")

    (site / ".nojekyll").write_text("", encoding="utf-8")
    util.log(f"P9 建站完成：首页 + 大模型专栏 + {len(tax['tracks'])} 个赛道页 + 看板 + 检索（展示周 {display_week}）")
