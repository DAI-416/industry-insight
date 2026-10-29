"""P2 清洗 + P3 去重：合成「归并组」，同事件多源报道合并为一条。"""
from __future__ import annotations

import datetime as dt
import difflib
import re

from . import util

# \w 在 Python3 默认包含中日韩文字，故 \W 恰好是「非中文非字母数字」的标点与空白
PUNCT_RE = re.compile(r"[\W_]+", re.UNICODE)
TOKEN_RE = re.compile(r"[\u4e00-\u9fa5]{2,}|[A-Za-z][A-Za-z0-9.+-]{1,}")

LEVEL_WEIGHT = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "E": 0}


def _norm_title(t: str) -> str:
    return PUNCT_RE.sub("", t or "").lower()


def _tokens(t: str) -> set[str]:
    return {m.group(0).lower() for m in TOKEN_RE.finditer(t or "")}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def filter_items(items: list[dict], filters: dict) -> tuple[list[dict], dict]:
    """关键词过滤与长度门槛。"""
    bl = filters.get("blacklist", [])
    wl = filters.get("whitelist", [])
    min_len = filters.get("min_length", {})
    drop_below = int(min_len.get("drop_below", 60))
    thin_below = int(min_len.get("thin_below", 200))

    kept, dropped = [], {"blacklist": 0, "short": 0}
    for it in items:
        text = f"{it['title']} {it.get('summary', '')}"
        if any(k in text for k in bl) and not any(w in text for w in wl):
            dropped["blacklist"] += 1
            continue
        body = it.get("content") or ""
        if len(body) < drop_below and len(it.get("summary") or "") < drop_below:
            dropped["short"] += 1
            continue
        it["thin"] = len(body) < thin_below
        kept.append(it)
    return kept, dropped


def _similar(a: dict, b: dict, cfg: dict) -> bool:
    ta, tb = _norm_title(a["title"]), _norm_title(b["title"])
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    ratio = difflib.SequenceMatcher(None, ta, tb).ratio()
    if ratio >= float(cfg.get("title_similarity", 0.82)):
        return True
    jac = _jaccard(_tokens(a["title"]), _tokens(b["title"]))
    return jac >= float(cfg.get("token_jaccard", 0.70)) and ratio >= 0.55


def _merge(members: list[dict]) -> dict:
    """组内择优：信源等级高优先，同级取正文更长者作为主条目。"""
    members = sorted(
        members,
        key=lambda x: (LEVEL_WEIGHT.get(x["source_level"], 0), len(x.get("content") or "")),
        reverse=True,
    )
    main = dict(members[0])
    main["sources"] = [
        {"id": m["source_id"], "name": m["source_name"], "level": m["source_level"],
         "url": m["url"], "title": m["title"], "published_at": m["published_at"]}
        for m in members
    ]
    main["source_count"] = len(members)
    # 补足正文：主条目正文过短时用组内最长的补齐
    longest = max(members, key=lambda x: len(x.get("content") or ""))
    if len(main.get("content") or "") < len(longest.get("content") or ""):
        main["content"] = longest["content"]
    if not main.get("summary"):
        main["summary"] = longest.get("summary", "")
    return main


def dedupe(items: list[dict], cfg: dict, window_days: int = 7) -> tuple[list[dict], int]:
    """返回 (归并组列表, 被合并掉的条目数)。"""
    if not items:
        return [], 0

    items = sorted(items, key=lambda x: x.get("published_at", ""), reverse=True)
    groups: list[list[dict]] = []
    merged_count = 0

    for it in items:
        placed = False
        it_time = util.parse_dt(it.get("published_at", "")) or util.now()
        for g in groups:
            head = g[0]
            head_time = util.parse_dt(head.get("published_at", "")) or util.now()
            if abs((it_time - head_time).total_seconds()) > window_days * 86400:
                continue
            if _similar(it, head, cfg):
                g.append(it)
                placed = True
                merged_count += 1
                break
        if not placed:
            groups.append([it])

    return [_merge(g) for g in groups], merged_count


def run(raw_items: list[dict]) -> tuple[list[dict], dict]:
    filters = util.load_config("filters")
    kept, dropped = filter_items(raw_items, filters)
    util.log(f"P2 清洗：保留 {len(kept)} 条，黑名单剔除 {dropped['blacklist']}，过短剔除 {dropped['short']}")

    grouped, merged = dedupe(kept, filters.get("dedupe", {}), int(filters.get("dedupe", {}).get("window_days", 7)))
    util.log(f"P3 去重：{len(kept)} 条 → {len(grouped)} 个归并组（合并 {merged} 条）")
    return grouped, {"dropped": dropped, "merged": merged, "in": len(raw_items), "out": len(grouped)}
