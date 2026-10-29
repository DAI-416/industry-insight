"""P4 分类：批量判定 赛道 / 市场 / 内容类型。

性能设计：一次请求处理 BATCH 条，把 150 条的分类从 150 次调用压到 15 次。
逐条调用在 Actions 环境实测要 10 分钟以上，批量后可控制在 1 分钟内。

策略：
  - 有 Gemini 时优先 LLM 批量；某条失败或缺失时回退规则
  - 无 Gemini 时纯规则，置信度按命中强度估算
  - 置信度 < min_confidence → status=pending_classify（不发布）
"""
from __future__ import annotations

from . import gemini, util

STRONG_W = 3
WEAK_W = 1
MIN_CONF = 0.6
BATCH = 10


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

    margin = (top_score - second) / top_score
    density = min(1.0, top_score / 6)
    confidence = round(min(0.95, 0.62 + 0.25 * margin + 0.13 * density), 3)
    return {"track_id": top_id, "confidence": confidence, "method": "rules"}


def detect_market(text: str, tax: dict) -> tuple[str, list[str]]:
    hit: list[str] = []
    for m in tax["markets"]:
        kws = (m.get("strong") or []) + (m.get("keywords") or [])
        if any(k in text for k in kws):
            hit.append(m["id"])
    if not hit:
        return "M-GL", []
    return hit[0], [x for x in hit[1:] if x != hit[0]]


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


# ---------------- LLM 批量分类 ----------------

PROMPT = """你是金融与科技资讯的分类助手。下面是 {n} 条资讯，请逐条判断归属。

可选赛道（每条只能选一个 ID）：
{tracks}

可选市场：M-A（A股） M-HK（港股） M-CN（美股中概） M-GL（全球）
内容类型：fact（政策/并购/融资/技术发布等事实）/ opinion（观点、研报、评论、预测）

{items}

严格输出 JSON，不要任何解释文字：
{{"results":[{{"i":1,"track_id":"赛道ID","market":"市场ID","content_type":"fact","confidence":0.8}}]}}"""


def _build_batch_prompt(batch: list[dict], tracks_desc: str) -> str:
    lines = []
    for idx, it in enumerate(batch, 1):
        body = (it.get("content") or it.get("summary") or "")[:300].replace("\n", " ")
        lines.append(f'[{idx}] 标题：{it["title"]}\n    正文：{body}')
    return PROMPT.format(n=len(batch), tracks=tracks_desc, items="\n".join(lines))


def classify_batch_by_llm(batch: list[dict], tax: dict, cfg: dict) -> dict[int, dict]:
    """返回 {批次内序号(1-based): 分类结果}"""
    tracks_desc = "\n".join(
        f'- {t["id"]}: {t["name"]}（{t.get("scope", "")}）' for t in tax["tracks"]
    )
    prompt = _build_batch_prompt(batch, tracks_desc)
    raw = gemini.generate(prompt, cfg, purpose="classify")
    data = gemini.extract_json(raw)
    if not data or "results" not in data:
        return {}

    valid = {t["id"] for t in tax["tracks"]}
    out: dict[int, dict] = {}
    for row in data["results"]:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("i"))
        except (TypeError, ValueError):
            continue
        if not (1 <= idx <= len(batch)):
            continue
        track_id = str(row.get("track_id", "")).strip()
        if track_id not in valid:
            continue
        market = str(row.get("market", "M-GL")).strip()
        if market not in {"M-A", "M-HK", "M-CN", "M-GL"}:
            market = "M-GL"
        ctype = str(row.get("content_type", "fact")).strip()
        if ctype not in {"fact", "opinion"}:
            ctype = "fact"
        try:
            conf = float(row.get("confidence", 0.75))
        except (TypeError, ValueError):
            conf = 0.75
        out[idx] = {"track_id": track_id, "market": market, "content_type": ctype,
                    "confidence": round(min(0.99, max(0.0, conf)), 3), "method": "llm"}
    return out


# ---------------- 入口 ----------------

def run(items: list[dict], sources_cfg: dict) -> tuple[list[dict], dict]:
    tax = util.load_taxonomy()
    cfg = util.load_llm()
    min_conf = float(cfg.get("fallback", {}).get("min_confidence", MIN_CONF))
    use_llm = gemini.available(cfg)

    src_tracks = {s["id"]: s.get("tracks", []) for s in sources_cfg["sources"]}
    for it in items:
        it["tracks_hint"] = src_tracks.get(it["source_id"], [])

    stats = {"llm": 0, "rules": 0, "low_conf": 0, "batches": 0, "batch_failed": 0}
    mode = "Gemini 批量" if use_llm else "规则模式（无 API Key）"
    util.log(f"P4 分类：{mode}，共 {len(items)} 条，批大小 {BATCH}")

    # 预置规则结果，LLM 成功时覆盖（保证任何一条都有兜底）
    for it in items:
        r = classify_by_rules(it, tax)
        it["_rule"] = r

    llm_results: dict[int, dict] = {}
    if use_llm:
        for start in range(0, len(items), BATCH):
            batch = items[start:start + BATCH]
            if not gemini.available(cfg):
                util.log("  LLM 已熔断，剩余条目走规则分类")
                break
            got = classify_batch_by_llm(batch, tax, cfg)
            stats["batches"] += 1
            if not got:
                stats["batch_failed"] += len(batch)
            for idx, res in got.items():
                llm_results[start + idx - 1] = res
            util.log(f"  批次 {stats['batches']}：{len(got)}/{len(batch)} 条由模型判定")

    for i, it in enumerate(items):
        text = f"{it['title']} {it.get('summary', '')} {it.get('content', '')[:1200]}"
        res = llm_results.get(i)
        if res:
            stats["llm"] += 1
            track_id, conf = res["track_id"], res["confidence"]
            market = res["market"]
            related = [m for m in detect_market(text, tax)[1] if m != market]
            ctype = res["content_type"]
            method = "llm"
        else:
            r = it["_rule"]
            stats["rules"] += 1
            track_id, conf = r["track_id"], r["confidence"]
            market, related = detect_market(text, tax)
            ctype = detect_content_type(text, tax)
            method = r["method"]

        it.pop("_rule", None)
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
