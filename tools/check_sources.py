"""信源体检：逐个探测 RSS 可用性，回写 status 字段。

用法：
    python3 tools/check_sources.py            # 全量体检
    python3 tools/check_sources.py --dry-run  # 只报告不写回
"""
import concurrent.futures as cf
import pathlib
import re
import sys
import urllib.request
import urllib.error

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = ROOT / "config" / "sources.yml"


def probe(src: dict, timeout: int, ua: str) -> tuple[str, bool, str]:
    """返回 (id, ok, detail)"""
    url = src["url"]
    if src.get("type") != "rss":
        return src["id"], False, "html 类型，本版本不解析（需接 RSSHub）"
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(400_000)
        head = body[:2000].decode("utf-8", "ignore")
        if not re.search(r"<(rss|feed|rdf:RDF)", head, re.I):
            return src["id"], False, f"返回非 RSS 内容（{len(body)} bytes）"
        n_items = len(re.findall(r"<item[ >]|<entry[ >]", body.decode("utf-8", "ignore"), re.I))
        if n_items == 0:
            return src["id"], False, "RSS 结构存在但无条目"
        return src["id"], True, f"ok · {n_items} items"
    except urllib.error.HTTPError as e:
        return src["id"], False, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return src["id"], False, f"{type(e).__name__}: {e}"[:70]


def main() -> None:
    dry = "--dry-run" in sys.argv
    cfg = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    settings = cfg["settings"]
    sources = cfg["sources"]

    results: dict[str, tuple[bool, str]] = {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {
            ex.submit(probe, s, settings["timeout_sec"], settings["user_agent"]): s["id"]
            for s in sources
        }
        for f in cf.as_completed(futs):
            sid, ok, detail = f.result()
            results[sid] = (ok, detail)

    ok_cnt = 0
    print(f"{'STATUS':<8}{'SOURCE':<18}{'DETAIL'}")
    print("-" * 78)
    for s in sources:
        ok, detail = results[s["id"]]
        ok_cnt += ok
        mark = "✅ OK" if ok else "❌ FAIL"
        print(f"{mark:<8}{s['name']:<18}{detail}")

    print("-" * 78)
    print(f"可用 {ok_cnt} / {len(sources)}")

    if dry:
        print("\n[--dry-run] 未写回配置")
        return

    for s in sources:
        ok, _ = results[s["id"]]
        s["status"] = "active" if ok else "pending"
    SOURCES.write_text(
        yaml.dump(cfg, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    print(f"\n已回写 {SOURCES}（active {ok_cnt} 个）")


if __name__ == "__main__":
    main()
