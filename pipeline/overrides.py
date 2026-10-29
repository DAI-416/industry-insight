"""修正层：应用 data/overrides.yml 的五种人工操作。

op: pin / recategorize / rescore / delete / add
格式错误或引用不存在的 ID 时跳过并在日志报错，不影响构建。
"""
from __future__ import annotations

import pathlib

import yaml

from . import util

OVERRIDES = util.DATA_DIR / "overrides.yml"
MANUAL_DIR = util.DATA_DIR / "manual"


def load() -> list[dict]:
    if not OVERRIDES.exists():
        return []
    try:
        data = yaml.safe_load(OVERRIDES.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        util.log(f"  overrides.yml 解析失败，已跳过：{e}")
        return []
    if not data:
        return []
    if not isinstance(data, list):
        util.log("  overrides.yml 顶层应为列表，已跳过")
        return []
    return [r for r in data if isinstance(r, dict)]


def _manual_items(week: str) -> list[dict]:
    """从 data/manual/*.md 读取人工补录，约定每段以 --- 分隔，用简单 key: value 头。"""
    out = []
    if not MANUAL_DIR.exists():
        return out
    for f in sorted(MANUAL_DIR.glob("*.md")):
        # 跳过示例文件，避免示例条目被当作真实数据发布
        if f.name.startswith("_") or ".example" in f.name:
            continue
        text = f.read_text(encoding="utf-8")
        for block in text.split("\n---\n"):
            meta, _, body = block.partition("\n\n")
            fields: dict[str, str] = {}
            for line in meta.splitlines():
                if ":" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition(":")
                    fields[k.strip().lower()] = v.strip()
            if not fields.get("title") or not fields.get("url"):
                continue
            out.append({
                "title": fields["title"],
                "url": fields["url"],
                "track_id": fields.get("track", ""),
                "market_primary": fields.get("market", "M-A"),
                "content_type": fields.get("type", "fact"),
                "importance_score": int(fields.get("score", 60) or 60),
                "ai_summary": fields.get("summary") or util.first_sentence(body),
                "source_name": "人工补录",
                "source_level": "C",
                "week_key": fields.get("week", week),
                "status": "published",
                "is_manual": True,
            })
    return out


def apply(items: list[dict], week: str) -> tuple[list[dict], dict]:
    rules = load()
    stat = {"applied": 0, "skipped": 0, "pinned": 0, "added": 0}

    by_id = {it.get("id"): it for it in items}

    for r in rules:
        op = str(r.get("op", "")).strip()
        rid = r.get("id")
        target = by_id.get(rid)
        if op in ("pin", "recategorize", "rescore", "delete") and target is None:
            util.log(f"  override 跳过：{op} 引用了不存在的 id={rid}")
            stat["skipped"] += 1
            continue

        if op == "pin":
            target["pinned"] = True
            stat["pinned"] += 1
        elif op == "recategorize":
            for k_src, k_dst in (("track", "track_id"), ("market", "market_primary"),
                                 ("content_type", "content_type")):
                if r.get(k_src):
                    target[k_dst] = r[k_src]
            target["human_edited"] = True
        elif op == "rescore":
            try:
                target["importance_score"] = int(r["score"])
                s = target["importance_score"]
                target["importance_level"] = (
                    "critical" if s >= 75 else "important" if s >= 60
                    else "normal" if s >= 40 else "low")
                target["human_edited"] = True
            except (KeyError, ValueError, TypeError):
                util.log(f"  override 跳过：rescore 缺少有效 score（id={rid}）")
                stat["skipped"] += 1
                continue
        elif op == "delete":
            target["status"] = "discarded"
            target["discard_reason"] = r.get("reason", "人工删除")
        elif op == "add":
            if not r.get("title") or not r.get("url"):
                util.log("  override 跳过：add 缺少 title 或 url")
                stat["skipped"] += 1
                continue
            wk = r.get("week", week)
            items.append({
                "id": util.event_id(wk, r["url"]),
                "title": r["title"],
                "url": r["url"],
                "track_id": r.get("track", ""),
                "market_primary": r.get("market", "M-A"),
                "market_related": r.get("market_related", []),
                "content_type": r.get("type", "fact"),
                "importance_score": int(r.get("score", 60)),
                "importance_level": "important",
                "ai_summary": r.get("summary") or util.first_sentence(r["title"]),
                "summary_method": "manual",
                "source_name": "人工补录",
                "source_level": "C",
                "source_count": 1,
                "sources": [{"name": "人工补录", "url": r["url"], "level": "C"}],
                "published_at": util.now().isoformat(),
                "week_key": wk,
                "status": "published",
                "is_manual": True,
            })
            stat["added"] += 1
        else:
            util.log(f"  override 跳过：未知操作 {op}")
            stat["skipped"] += 1
            continue
        stat["applied"] += 1

    manual = _manual_items(week)
    if manual:
        items.extend(manual)
        stat["added"] += len(manual)

    util.log(f"修正层：应用 {stat['applied']} 条规则，补录 {stat['added']} 条，跳过 {stat['skipped']} 条")
    return items, stat
