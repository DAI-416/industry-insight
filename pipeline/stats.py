"""P8 统计：看板所需的全部指标，全部由代码计算，不经 LLM。

产出 data/stats/ 下的 JSON，构建站点时直接读取。
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from . import util

# 活跃度口径（PRD §5.2）：Σ(事实类重要度分) × 0.6 + 事实类条目数 × 10 × 0.4
W_SCORE = 0.6
W_COUNT = 4.0  # 10 × 0.4

# 停用词：通用词 + 地名 + 星期月份。地名必须排除——否则 SCMP/Nikkei 的
# 标题会让 "Hong Kong" "China" "Asia" 长期占据高频实体榜首，无信息量。
EN_STOP = {
    # 通用
    "the", "and", "for", "with", "from", "that", "this", "will", "are", "was",
    "has", "have", "not", "but", "its", "you", "can", "how", "why", "what",
    "new", "may", "now", "our", "out", "all", "who", "top", "get", "one",
    "two", "his", "her", "they", "their", "more", "than", "into", "over",
    # 地名与区域
    "hong", "kong", "china", "chinese", "asia", "asian", "beijing", "shanghai",
    "shenzhen", "guangzhou", "taiwan", "japan", "japanese", "korea", "korean",
    "india", "indian", "thailand", "indonesia", "vietnam", "singapore",
    "malaysia", "philippines", "southeast", "europe", "european", "america",
    "american", "britain", "british", "germany", "french", "russia", "ukraine",
    "israel", "saudi", "uae", "africa", "latin", "west", "east", "north",
    "south", "global", "world", "international", "city", "province",
    # 时间
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "oct", "nov", "dec", "year", "month", "week",
    "day", "today", "yesterday", "tomorrow", "first", "second", "third",
    # 泛化词
    "report", "reports", "news", "said", "says", "according", "company",
    "companies", "business", "market", "markets", "analyst", "analysts",
    # 公司名片段与国名拆分残留（United States 会被拆成两个词）
    "united", "states", "security", "court", "holdings", "group", "capital",
    "partners", "ventures", "technologies", "systems", "labs", "global",
    "daily", "times", "post", "journal", "week", "weekend", "morning",
    "street", "week", "review", "digest", "insight", "media", "hold",
    "gp", "lp", "wang", "president", "minister", "chief", "chairman",
    "asean", "indonesian", "malaysian", "thai", "vietnamese",
    "says", "told", "adds", "update", "live", "video", "photo",
}

# 术语表里存在但做热词没有信息量的缩写
TERM_SKIP = {"GP", "LP", "PC", "AR", "VR", "MR", "XR", "IDC", "IP核", "L2", "L3", "L4"}

# 中文低信息词：纯判断语气词，做热词没有意义
CN_SKIP = {
    "上调", "下调", "预计", "看好", "认为", "表示", "判断", "值得关注",
    "建议关注", "分析认为", "坦言", "预期", "展望", "点评",
}
EN_ENTITY = re.compile(r"\b([A-Z][A-Za-z0-9&.\-]{2,})\b")


def activity(facts: list[dict]) -> float:
    return round(sum(f.get("importance_score", 0) for f in facts) * W_SCORE
                 + len(facts) * W_COUNT, 1)


def _entities(items: list[dict], tax: dict, limit: int = 40) -> list[dict]:
    """本周热词：按「出现在多少条新闻里」计数（文档频次），而非词频总数。

    用文档频次而非出现次数，避免单条长文反复提及同一个词就把榜单刷满。
    候选词 = 赛道术语（领域内专有名词）+ 英文专名。
    """
    df: Counter[str] = Counter()
    for it in items:
        text = f"{it.get('title', '')} {it.get('ai_summary', '')}"
        seen: set[str] = set()
        for tr in tax["tracks"]:
            for kw in (tr.get("strong") or []) + (tr.get("keywords") or []):
                if len(kw) >= 2 and kw not in CN_SKIP and kw not in TERM_SKIP and kw in text:
                    seen.add(kw)
        for m in EN_ENTITY.finditer(text):
            word = m.group(1).strip(".")
            if len(word) >= 4 and word.lower() not in EN_STOP:
                seen.add(word)
        for word in seen:
            df[word] += 1
    return [{"name": k, "count": v} for k, v in df.most_common(limit) if v >= 2]


def weekly(items: list[dict], week: str, tax: dict) -> dict:
    wk_items = [i for i in items if i.get("week_key") == week and i.get("status") == "published"]
    facts = [i for i in wk_items if i.get("content_type") == "fact"]
    opinions = [i for i in wk_items if i.get("content_type") == "opinion"]

    by_track: dict[str, list[dict]] = defaultdict(list)
    for i in facts:
        by_track[i.get("track_id", "")].append(i)

    # OTHER-1 是兜底类，不进活跃度排行与自动摘要，避免"其他领域"霸占榜首
    other_facts = by_track.get("OTHER-1", [])
    track_activity = []
    for t in tax["tracks"]:
        if t["id"] == "OTHER-1":
            continue
        f = by_track.get(t["id"], [])
        track_activity.append({
            "track_id": t["id"],
            "name": t["name"],
            "domain": t["domain"],
            "is_focus": bool(t.get("is_focus")),
            "count": len(f),
            "opinion_count": sum(1 for i in opinions if i.get("track_id") == t["id"]),
            "score": activity(f),
        })
    track_activity.sort(key=lambda x: x["score"], reverse=True)

    market_dist = Counter(i.get("market_primary", "M-GL") for i in wk_items)
    importance_dist = Counter(i.get("importance_level", "low") for i in facts)
    source_dist = Counter(i.get("source_name", "?") for i in wk_items)

    return {
        "week_key": week,
        "generated_at": util.now().isoformat(timespec="seconds"),
        "total": len(wk_items),
        "fact_count": len(facts),
        "opinion_count": len(opinions),
        "track_activity": track_activity,
        "market_dist": dict(market_dist),
        "importance_dist": dict(importance_dist),
        "source_dist": dict(source_dist),
        "top_entities": _entities(wk_items, tax),
        "total_score": round(sum(t["score"] for t in track_activity), 1),
        "other_count": len(other_facts),
        "other_opinion_count": sum(1 for i in opinions if i.get("track_id") == "OTHER-1"),
    }


def build_all(items: list[dict], weeks: list[str], tax: dict) -> dict:
    """返回 {weekly: {...}, timeseries: {...}, sources: {...}, summaries: {...}}"""
    weekly_map = {w: weekly(items, w, tax) for w in weeks}

    # 时序：每赛道逐周活跃度（用字典查，避免 OTHER-1 被排除后 index 越界）
    track_ids = [t["id"] for t in tax["tracks"] if t["id"] != "OTHER-1"]
    lookup = {w: {x["track_id"]: x for x in weekly_map[w]["track_activity"]} for w in weeks}
    timeseries = {
        "weeks": weeks,
        "tracks": {tid: [lookup[w].get(tid, {}).get("score", 0) for w in weeks]
                   for tid in track_ids},
        "counts": {tid: [lookup[w].get(tid, {}).get("count", 0) for w in weeks]
                   for tid in track_ids},
    }

    # 信源贡献（近 4 周）
    src_counter: Counter[str] = Counter()
    recent = weeks[-4:]
    for w in recent:
        for name, cnt in weekly_map[w]["source_dist"].items():
            src_counter[name] += cnt
    sources = [{"name": k, "count": v} for k, v in src_counter.most_common(10)]

    # D1-D6 自动摘要（纯统计）
    summaries: dict[str, dict] = {}
    for idx, w in enumerate(weeks):
        cur = weekly_map[w]
        prev = weekly_map[weeks[idx - 1]] if idx > 0 else None
        cur_act = {t["track_id"]: t for t in cur["track_activity"]}

        top3 = [t for t in cur["track_activity"] if t["count"] > 0][:3]

        up, down = None, None
        if prev:
            prev_act = {t["track_id"]: t for t in prev["track_activity"]}
            deltas = []
            for tid, t in cur_act.items():
                p = prev_act.get(tid, {"score": 0, "count": 0})
                if t["count"] >= 3 and p["score"] > 0:
                    deltas.append((tid, t["name"], round((t["score"] - p["score"]) / p["score"] * 100, 1)))
            if deltas:
                up = max(deltas, key=lambda x: x[2])
                down = min(deltas, key=lambda x: x[2])

        market_total = sum(cur["market_dist"].values()) or 1
        dominant = max(cur["market_dist"].items(), key=lambda kv: kv[1]) if cur["market_dist"] else ("M-GL", 0)
        market_names = {"M-A": "A股", "M-HK": "港股", "M-CN": "中概", "M-GL": "全球"}
        focus_critical = sum(
            1 for i in items
            if i.get("week_key") == w and i.get("status") == "published"
            and i.get("content_type") == "fact"
            and i.get("importance_level") == "critical"
            and any(t["id"] == i.get("track_id") and t.get("is_focus") for t in tax["tracks"])
        )

        d = []
        if top3:
            d.append({
                "id": "D1",
                "text": "本周最活跃赛道：" + "、".join(
                    f"{t['name']}（{t['count']} 条，活跃度 {t['score']:g}）" for t in top3),
            })
        if up and up[2] > 0:
            d.append({"id": "D2", "text": f"环比上升最快：{up[1]}（{up[2]:+.1f}%）"})
        if down and down[2] < 0:
            d.append({"id": "D3", "text": f"环比下降最快：{down[1]}（{down[2]:+.1f}%）"})
        d.append({
            "id": "D4",
            "text": f"本周共 {cur['total']} 条：事实 {cur['fact_count']} 条 / 观点 {cur['opinion_count']} 条",
        })
        d.append({
            "id": "D5",
            "text": "市场分布：" + " · ".join(
                f"{market_names.get(k, k)} {v} 条（{v / market_total * 100:.0f}%）"
                for k, v in sorted(cur["market_dist"].items(), key=lambda kv: -kv[1])),
        })
        d.append({
            "id": "D6",
            "text": f"核心赛道本周关键信号 {focus_critical} 条（重要度 ≥75）",
        })
        summaries[w] = {"week_key": w, "items": d}

    return {"weekly": weekly_map, "timeseries": timeseries,
            "sources": sources, "summaries": summaries}


def run(items: list[dict], weeks: list[str]) -> dict:
    tax = util.load_taxonomy()
    result = build_all(items, weeks, tax)
    util.STATS_DIR.mkdir(parents=True, exist_ok=True)
    util.write_json(util.STATS_DIR / "timeseries.json", result["timeseries"])
    util.write_json(util.STATS_DIR / "sources.json", result["sources"])
    util.write_json(util.STATS_DIR / "entities.json", result["weekly"][weeks[-1]]["top_entities"] if weeks else [])
    for w, data in result["weekly"].items():
        util.write_json(util.STATS_DIR / f"weekly_{w}.json", data)
    for w, data in result["summaries"].items():
        util.write_json(util.STATS_DIR / f"summary_{w}.json", data)
    util.log(f"P8 统计完成：{len(weeks)} 个周次，最新周活跃度合计 "
             f"{result['weekly'][weeks[-1]]['total_score'] if weeks else 0}")
    return result
