"""P5 重要度打分（仅 fact 类）。

五维：信源等级 25 / 事件类型 25 / 影响广度 20 / 报道密度 20 / 时效性 10
核心关注赛道 ×1.15（上限 100）
"""
from __future__ import annotations

from . import util

LEVEL_SCORE = {"S": 25, "A": 20, "B": 17, "C": 15, "D": 12, "E": 8}
BREADTH_GLOBAL = ["全行业", "产业链", "行业", "政策", "监管", "全国", "整个", "赛道", "板块", "市场格局"]


def event_type_score(text: str, tax: dict) -> tuple[int, str]:
    for et in tax.get("event_types", []):
        kws = et.get("keywords") or []
        if kws and any(k in text for k in kws):
            return int(et["score"]), et["name"]
    return 10, "常规经营"


def run(items: list[dict]) -> tuple[list[dict], dict]:
    tax = util.load_taxonomy()
    focus = {t["id"] for t in tax["tracks"] if t.get("is_focus")}
    now = util.now()

    for it in items:
        if it.get("content_type") == "opinion":
            it["importance_score"] = 0
            it["importance_level"] = "opinion"
            it["event_type"] = "观点评论"
            continue

        text = f"{it['title']} {it.get('summary', '')} {it.get('content', '')[:800]}"
        s_level = LEVEL_SCORE.get(it.get("source_level", "E"), 8)
        s_event, et_name = event_type_score(text, tax)
        s_breadth = 20 if any(k in text for k in BREADTH_GLOBAL) else 5
        s_density = min(20, (it.get("source_count", 1) - 1) * 7)
        pub = util.parse_dt(it.get("published_at", "")) or now
        hours = (now - pub).total_seconds() / 3600
        s_time = 10 if hours <= 24 else 5 if hours <= 168 else 2

        total = s_level + s_event + s_breadth + s_density + s_time
        if it.get("track_id") in focus:
            total = min(100, round(total * 1.15))

        it["importance_score"] = int(total)
        it["importance_level"] = (
            "critical" if total >= 75 else
            "important" if total >= 60 else
            "normal" if total >= 40 else "low"
        )
        it["event_type"] = et_name
        it["score_detail"] = {
            "source": s_level, "event": s_event, "breadth": s_breadth,
            "density": s_density, "timeliness": s_time, "focus_boost": it.get("track_id") in focus,
        }

    dist: dict[str, int] = {}
    for it in items:
        dist[it["importance_level"]] = dist.get(it["importance_level"], 0) + 1
    util.log(f"P5 打分完成：{dist}")
    return items, dist
