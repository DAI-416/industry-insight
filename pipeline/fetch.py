"""P1 采集：拉取 RSS/Atom 并解析为结构化条目。仅用标准库。

解析三级容错：
  1. 预清洗非法字符后走 ElementTree
  2. 修复裸 & 与未闭合 CDATA 后再试
  3. 正则兜底逐条提取
"""
from __future__ import annotations

import concurrent.futures as cf
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict

from . import util

ILLEGAL_XML = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)
BARE_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class RawItem:
    id: str
    source_id: str
    source_name: str
    source_level: str
    title: str
    url: str
    summary: str
    content: str
    published_at: str
    fetched_at: str
    date_assumed: bool = False


# ---------------- XML 容错 ----------------

def _sanitize(body: bytes) -> bytes:
    body = ILLEGAL_XML.sub(b"", body)
    try:
        txt = body.decode("utf-8")
    except UnicodeDecodeError:
        txt = body.decode("gb18030", "ignore")
    # 未闭合 CDATA：奇数个则补闭合
    if txt.count("<![CDATA[") > txt.count("]]>"):
        txt += "]]>"
    # 裸 & 转义（跳过已有实体）
    txt = BARE_AMP.sub("&amp;", txt)
    return txt.encode("utf-8")


def _parse_tree(body: bytes):
    for candidate in (body, _sanitize(body)):
        try:
            return ET.fromstring(candidate)
        except ET.ParseError:
            continue
    return None


# ---------------- 结构解析 ----------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_tree_items(root) -> list[dict]:
    out: list[dict] = []
    for node in root.iter():
        name = _local(node.tag)
        if name not in ("item", "entry"):
            continue
        rec = {"title": "", "url": "", "summary": "", "content": "", "published": ""}
        for child in node:
            cn = _local(child.tag)
            val = (child.text or "").strip()
            if cn == "title":
                rec["title"] = val
            elif cn == "link":
                href = child.get("href")
                rec["url"] = rec["url"] or (href or val)
            elif cn == "guid" and not rec["url"]:
                rec["url"] = val
            elif cn == "summary" or cn == "description":
                rec["summary"] = rec["summary"] or val
            elif cn == "encoded" or cn == "content":
                rec["content"] = rec["content"] or val
            elif cn in ("pubdate", "published", "updated", "date"):
                rec["published"] = rec["published"] or val
        out.append(rec)
    return out


BLOCK_RE = re.compile(r"<(item|entry)\b[^>]*>(.*?)</\1>", re.S | re.I)


def _tag(block: str, *names: str) -> str:
    for n in names:
        m = re.search(rf"<{n}\b[^>]*>(.*?)</{n}>", block, re.S | re.I)
        if m:
            v = CDATA_RE.sub(r"\1", m.group(1)).strip()
            if v:
                return v
        m = re.search(rf'<{n}\b[^>]*href="([^"]+)"', block, re.I)
        if m:
            return m.group(1).strip()
    return ""


def _parse_regex(text: str) -> list[dict]:
    out = []
    for m in BLOCK_RE.finditer(text):
        block = CDATA_RE.sub(r"\1", m.group(2))
        out.append({
            "title": _tag(block, "title"),
            "url": _tag(block, "link", "guid"),
            "summary": _tag(block, "description", "summary"),
            "content": _tag(block, "encoded", "content", "description", "summary"),
            "published": _tag(block, "pubDate", "published", "updated", "dc:date"),
        })
    return out


# ---------------- 单源采集 ----------------

def fetch_source(src: dict, settings: dict, window_days: int) -> tuple[list[RawItem], str]:
    if src.get("type") != "rss":
        return [], "skip:非RSS"
    if src.get("status") in ("paused",):
        return [], "skip:已停用"

    req = urllib.request.Request(
        src["url"],
        headers={
            "User-Agent": settings["user_agent"],
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    body, last_err = None, ""
    for _ in range(int(settings.get("retry", 2))):
        try:
            with urllib.request.urlopen(req, timeout=settings["timeout_sec"]) as r:
                body = r.read(3_000_000)
            break
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}:{str(e)[:60]}"
    if body is None:
        return [], f"fail:{last_err}"

    root = _parse_tree(body)
    recs = _parse_tree_items(root) if root is not None else []
    if not recs:
        txt = _sanitize(body).decode("utf-8", "ignore")
        recs = _parse_regex(txt)
    if not recs:
        return [], "fail:无条目"

    cutoff = util.now() - util.timedelta_days(window_days)
    items: list[RawItem] = []
    assumed = 0
    for e in recs:
        title = util.clean_text(CDATA_RE.sub(r"\1", e["title"]))
        url = (CDATA_RE.sub(r"\1", e["url"]) or "").strip()
        if not title or not url.startswith("http"):
            continue
        pub = util.parse_dt(e["published"])
        if pub is None:
            # 部分源（如日经亚洲）不提供发布日期，用抓取时间兜底并标记
            pub = util.now()
            assumed += 1
        if pub < cutoff:
            continue
        content = util.clean_text(CDATA_RE.sub(r"\1", e["content"]))
        summary = util.clean_text(CDATA_RE.sub(r"\1", e["summary"]))
        items.append(RawItem(
            id=util.sha(url, 12),
            source_id=src["id"],
            source_name=src["name"],
            source_level=src["level"],
            title=title,
            url=url,
            summary=summary[:600],
            content=(content or summary)[:4000],
            published_at=pub.isoformat(),
            fetched_at=util.now().isoformat(),
            date_assumed=bool(assumed and util.parse_dt(e["published"]) is None),
        ))
    note = f"ok:{len(recs)}条→{len(items)}条"
    if assumed:
        note += f"（{assumed}条无日期用抓取时间）"
    return items, note


def collect(sources_cfg: dict) -> tuple[list[dict], dict]:
    settings = sources_cfg["settings"]
    window = int(settings.get("window_days", 10))
    sources = sources_cfg["sources"]
    report: dict[str, str] = {}
    all_items: list[dict] = []

    active = sum(1 for s in sources if s.get("status") == "active")
    util.log(f"P1 采集：活动源 {active} 个，窗口 {window} 天")
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_source, s, settings, window): s for s in sources}
        for f in cf.as_completed(futs):
            src = futs[f]
            try:
                items, status = f.result()
            except Exception as e:  # noqa: BLE001
                items, status = [], f"fail:{type(e).__name__}"
            report[src["id"]] = status
            all_items.extend(asdict(i) for i in items)

    seen: dict[str, dict] = {}
    for it in all_items:
        seen.setdefault(it["url"], it)
    deduped = list(seen.values())
    util.log(f"P1 完成：{len(all_items)} 条 → URL 去重 {len(deduped)} 条")
    return deduped, report
