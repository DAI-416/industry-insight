"""P4 分类：判定 赛道 / 市场 / 内容类型。

策略：
  - 有 Gemini 时优先 LLM（要求返回 JSON），失败或置信度不足时回退规则
  - 无 Gemini 时纯规则，置信度按命中强度估算
  - 置信度 < min_confidence → status=pending_classify（不发布）
"""
from __future__ import annotations

from . import gemini, util

STRONG_W = 3
WEAK_W = 1
MIN_CONF = 0.6


# ---------------- 规则分类 ----------------

def _score_track(text: str, track: dict) -> float:
    score = 0.0
    for kw in track.get("strong", []) or []:
        if kw in text:
            score += STRONG_W
    for kw in track.get("keywords", []) or []:
        if kw in text:
            score += WEAK_W
    return score


def classify_by_rules(item: dict, tax: dict) -> dict:
    text = f"{item['title']} {item.get('summary', '')} {item.get('content', '')[:1200]}"
    scores = {t["id"]: _score_track(text, t) for t in tax["tracks"]}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_id, top_score = ranked[0] if ranked else ("", 0.0)
    second = ranked[1][1] if len(ranked) > 1 else 0.0

    if top_score <= 0:
        # 无任何关键词命中：在信源擅长的赛道里按命中数二次择优，仍为 0 则取第一个
        hints = item.get("tracks_hint") or []
        if hints:
            by_id = {t["id"]: t for t in tax["tracks"]}
            best = max(hints, key=lambda tid: _score_track(text, by_id.get(tid, {})))
            return {"track_id": best, "confidence": 0.62, "method": "rules:source_hint"}
        return {"track_id": "", "confidence": 0.2, "method": "rules:none"}

    # 有个关键词命中即给基础分，命中越集中、命中越多越可信
    margin = (top_score - second) / top_score
    density = min(1.0, top_score / 6)
    confidence = round(min(0.95, 0.62 + 0.25 * margin + 0.13 * density), 3)
    return {"track_id": top_id, "confidence": confidence, "method": "rules"}


def detect_market(text: str, tax: dict) -> tuple[str, list[str]]:
    """返回 (主市场, 关联市场)"""
    hit: list[str] = []
    for m in tax["markets"]:
        kws = (m.get("strong") or []) + (m.get("keywords") or [])
        if any(k in text for k in kws):
            hit.append(m["id"])
    if not hit:
        return "M-GL", []
    primary = hit[0]
    return primary, [x for x in hit[1:] if x != primary]


FACT_STRONG = ["发布", "出台", "宣布", "签署", "完成", "收购", "起诉", "召回",
               "获批", "落地", "投产", "量产", "融资", "上市", "递表", "处罚", "立案"]


def detect_content_type(text: str, tax: dict) -> str:
    markers = sum(1 for k in tax.get("opinion_markers", []) if k in text)
    facts = sum(1 for k in FACT_STRONG if k in text)
    if markers >= 1 and facts == 0:
        return "opinion"
    if markers >= 2 and facts <= 1:
        return "opinion"
    return "fact"


# ---------------- LLM 分类 ----------------

PROMPT = """你是金融与科技行业的资讯分类助手。请判断下面这条资讯的归属。

可选赛道（只能选一个）：
{tracks}

可选市场：M-A（A股） M-HK（港股） M-CN（美股中概） M-GL（全球）
内容类型：fact（事实事件，如政策发布、并购、融资、技术发布）/ opinion（观点、研报、评论、预测）

标题：{title}
正文片段：{body}

严格输出 JSON，不要解释：
{{"track_id": "赛道ID", "market": "市场ID", "content_type": "fact或opinion", "confidence": 0.0到1.0的小数}}"""


def classify_by_llm(item: dict, tax: dict, cfg: dict) -> dict | None:
    track_lines = "\n".join(
        f'- {t["id"]}: {t["name"]}（{t.get("scope", "")}）' for t in tax["tracks"]
    )
    prompt = PROMPT.format(
        tracks=track_lines,
        title=item["title"],
        body=(item.get("content") or item.get("summary") or "")[:800],
    )
    raw = gemini.generate(prompt, cfg, purpose="classify")
    data = gemini.extract_json(raw)
    if not data:
        return None
    track_id = str(data.get("track_id", "")).strip()
    valid = {t["id"] for t in tax["tracks"]}
    if track_id not in valid:
        return None
    market = str(data.get("market", "M-GL")).strip()
    if market not in {"M-A", "M-HK", "M-CN", "M-GL"}:
        market = "M-GL"
    ctype = str(data.get("content_type", "fact")).strip()
    if ctype not in {"fact", "opinion"}:
        ctype = "fact"
    try:
        conf = float(data.get("confidence", 0.7))
    except (TypeError, ValueError):
        conf = 0.7
    return {"track_id": track_id, "market": market, "content_type": ctype,
            "confidence": round(min(0.99, max(0.0, conf)), 3), "method": "llm"}


# ---------------- 入口 ----------------

def run(items: list[dict], sources_cfg: dict) -> tuple[list[dict], dict]:
    tax = util.load_taxonomy()
    cfg = util.load_llm()
    min_conf = float(cfg.get("fallback", {}).get("min_confidence", MIN_CONF))
    use_llm = gemini.available(cfg)

    src_tracks = {s["id"]: s.get("tracks", []) for s in sources_cfg["sources"]}
    for it in items:
        it["tracks_hint"] = src_tracks.get(it["source_id"], [])

    stats = {"llm": 0, "rules": 0, "low_conf": 0}
    util.log(f"P4 分类：{'Gemini' if use_llm else '规则模式（无 API Key）'}，共 {len(items)} 条")

    for it in items:
        text = f"{it['title']} {it.get('summary', '')} {it.get('content', '')[:1200]}"
        result = classify_by_llm(it, tax, cfg) if (use_llm and gemini.available(cfg)) else None
        if result:
            stats["llm"] += 1
            track_id, conf = result["track_id"], result["confidence"]
            market, related = result["market"], detect_market(text, tax)[1]
            ctype = result["content_type"]
            method = "llm"
        else:
            r = classify_by_rules(it, tax)
            stats["rules"] += 1
            track_id, conf = r["track_id"], r["confidence"]
            market, related = detect_market(text, tax)
            ctype = detect_content_type(text, tax)
            method = r["method"]

        it.update({
            "track_id": track_id,
            "market_primary": market,
            "market_related": related,
            "content_type": ctype,
            "classify_confidence": conf,
            "classify_method": method,
        })
        it["status"] = "published" if conf >= min_conf and track_id else "pending_classify"
        if it["status"] != "published":
            stats["low_conf"] += 1

    util.log(f"P4 完成：LLM {stats['llm']} / 规则 {stats['rules']} / 待归类 {stats['low_conf']}")
    return items, stats
