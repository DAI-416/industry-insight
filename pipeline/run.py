"""编排入口：P1→P9 全链路。

用法：
    python3 -m pipeline.run                # 完整跑：采集 → 处理 → 统计 → 建站
    python3 -m pipeline.run --no-fetch     # 不采集，用 data/raw 最新快照
    python3 -m pipeline.run --build-only   # 只重建站点（改样式/改 overrides 后用）
    python3 -m pipeline.run --weeks 12     # 统计窗口周数（默认 12）
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from . import classify, clean, fetch, overrides, score, stats, summarize, util


# ---------------- 事件库读写 ----------------

def load_all_events() -> list[dict]:
    out: list[dict] = []
    for f in sorted(util.EVENTS_DIR.glob("*.json")):
        data = util.read_json(f, default={}) or {}
        out.extend(data.get("events", []))
    return out


def merge_into_week(new_items: list[dict]) -> dict[str, int]:
    """按 week_key 分桶并合并进已有周文件。返回 {week: 新增条数}"""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for it in new_items:
        pk = util.week_key(util.parse_dt(it["published_at"]) or util.now())
        it["week_key"] = pk
        buckets[pk].append(it)

    added: dict[str, int] = {}
    for wk, items in buckets.items():
        path = util.EVENTS_DIR / f"{wk}.json"
        existing = util.read_json(path, default={}) or {}
        old: list[dict] = existing.get("events", [])
        by_key = {e.get("id") or e.get("url"): e for e in old}

        fresh = 0
        for it in items:
            key = it.get("id") or it.get("url")
            if key in by_key:
                # 已存在：保留人工修正字段，其余更新
                prev = by_key[key]
                for f in ("pinned", "human_edited", "discard_reason"):
                    if f in prev:
                        it[f] = prev[f]
                if prev.get("human_edited"):
                    for f in ("track_id", "market_primary", "content_type",
                              "importance_score", "importance_level", "ai_summary"):
                        if f in prev:
                            it[f] = prev[f]
                if prev.get("status") == "discarded":
                    it["status"] = "discarded"
                it["id"] = prev.get("id", key)
                by_key[key] = it
            else:
                it["id"] = it.get("id") or util.event_id(wk, it["url"])
                by_key[key] = it
                fresh += 1

        merged = list(by_key.values())
        util.write_json(path, {
            "week_key": wk,
            "generated_at": util.now().isoformat(timespec="seconds"),
            "events": merged,
        })
        added[wk] = fresh
    return added


# ---------------- 主流程 ----------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--weeks", type=int, default=12)
    args = ap.parse_args()

    util.log("=" * 56)
    util.log("行业洞察周报 · 管线启动")

    run_log: dict = {"started_at": util.now().isoformat(timespec="seconds"), "stages": {}}

    if args.build_only:
        util.log("跳过采集与处理，仅重建站点")
    else:
        sources_cfg = util.load_sources()

        # P1
        if args.no_fetch:
            raw_path = sorted((util.DATA_DIR / "raw").glob("*.jsonl"))[-1]
            raw = util.read_jsonl(raw_path)
            util.log(f"P1 跳过采集，复用 {raw_path.name}：{len(raw)} 条")
            run_log["stages"]["fetch"] = {"mode": "reuse", "in": len(raw)}
        else:
            raw, report = fetch.collect(sources_cfg)
            util.write_jsonl(util.DATA_DIR / "raw" / f"{util.now():%Y-%m-%d}.jsonl", raw)
            run_log["stages"]["fetch"] = {"in": len(raw), "sources": report}

        # P2 + P3
        grouped, clean_stat = clean.run(raw)
        run_log["stages"]["clean"] = clean_stat

        # P4
        grouped, cls_stat = classify.run(grouped, sources_cfg)
        run_log["stages"]["classify"] = cls_stat

        # P5
        grouped, score_dist = score.run(grouped)
        run_log["stages"]["score"] = score_dist

        # P6 + P7
        grouped, sum_stat = summarize.run(grouped)
        run_log["stages"]["summarize"] = sum_stat

        # 入库
        added = merge_into_week(grouped)
        util.log(f"入库：{sum(added.values())} 条新增，涉及 {len(added)} 个周次")
        run_log["stages"]["store"] = added

    # 修正层（对全库应用，保证历史修正不丢）
    all_events = load_all_events()
    current_week = util.week_key(util.now())
    all_events, ov_stat = overrides.apply(all_events, current_week)
    run_log["stages"]["overrides"] = ov_stat

    # 重新按周写回（overrides 可能改变归属周）
    by_week: dict[str, list[dict]] = defaultdict(list)
    for e in all_events:
        by_week[e.get("week_key") or current_week].append(e)
    for wk, evs in by_week.items():
        util.write_json(util.EVENTS_DIR / f"{wk}.json", {
            "week_key": wk,
            "generated_at": util.now().isoformat(timespec="seconds"),
            "events": evs,
        })

    # P8 统计
    weeks = util.last_n_weeks(current_week, args.weeks)
    # 只保留有数据的周次 + 最近窗口
    stat_result = stats.run(all_events, weeks)
    run_log["stages"]["stats"] = {"weeks": len(weeks),
                                  "total_events": len(all_events)}

    # P9 建站
    from . import build_site
    build_site.run(all_events, stat_result, weeks, current_week)

    run_log["finished_at"] = util.now().isoformat(timespec="seconds")
    run_log["status"] = "success"
    util.write_json(util.RUNS_DIR / f"{util.now():%Y%m%d-%H%M%S}.json", run_log)

    util.log("管线完成 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
