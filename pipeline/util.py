"""通用工具：路径、配置加载、日志、周次计算、文本清洗。"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import json
import pathlib
import re
import unicodedata

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
EVENTS_DIR = DATA_DIR / "events"
STATS_DIR = DATA_DIR / "stats"
RUNS_DIR = DATA_DIR / "runs"
SITE_DIR = ROOT / "site"

TZ = dt.timezone(dt.timedelta(hours=8))  # Asia/Shanghai


# ---------------- 配置 ----------------

def load_config(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / f"{name}.yml").read_text(encoding="utf-8"))


def load_taxonomy() -> dict:
    return load_config("taxonomy")


def load_sources() -> dict:
    return load_config("sources")


def load_llm() -> dict:
    return load_config("llm")


# ---------------- 时间 ----------------

def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def timedelta_days(n: int) -> dt.timedelta:
    return dt.timedelta(days=n)


def week_key(d: dt.datetime | dt.date) -> str:
    """ISO 周，如 2026-W44"""
    if isinstance(d, dt.datetime):
        d = d.date()
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def week_bounds(wk: str) -> tuple[dt.date, dt.date]:
    """返回该 ISO 周的周一与周日"""
    year, w = wk.split("-W")
    monday = dt.date.fromisocalendar(int(year), int(w), 1)
    return monday, monday + dt.timedelta(days=6)


def prev_week(wk: str) -> str:
    monday, _ = week_bounds(wk)
    return week_key(monday - dt.timedelta(days=7))


def last_n_weeks(wk: str, n: int) -> list[str]:
    """返回截至 wk（含）的最近 n 个周次，升序"""
    out = [wk]
    cur = wk
    for _ in range(n - 1):
        cur = prev_week(cur)
        out.append(cur)
    return list(reversed(out))


def parse_dt(text: str) -> dt.datetime | None:
    """解析 RSS 常见时间格式。

    优先用 email.utils（RFC 822/2822，不依赖系统 locale），
    再兜底几种 ISO 与中文格式。
    """
    if not text:
        return None
    text = text.strip()

    # RFC 822：Wed, 29 Oct 2026 07:00:00 +0900 / GMT 等
    if "," in text or re.match(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}", text):
        try:
            d = email.utils.parsedate_to_datetime(text)
            if d:
                return d if d.tzinfo else d.replace(tzinfo=TZ)
        except (TypeError, ValueError):
            pass

    fmts = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
        "%Y年%m月%d日",
    ]
    for f in fmts:
        try:
            d = dt.datetime.strptime(text, f)
            return d if d.tzinfo else d.replace(tzinfo=TZ)
        except ValueError:
            continue

    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})", text)
    if m:
        return dt.datetime(*map(int, m.groups()), tzinfo=TZ)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return dt.datetime(*map(int, m.groups()), tzinfo=TZ)
    return None


# ---------------- 文本 ----------------

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\u3000]+")
NB_RE = re.compile(r"[\u00a0\u200b\ufeff]")


def strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>", "\n", s, flags=re.I)
    s = TAG_RE.sub("", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
          .replace("&ldquo;", "“").replace("&rdquo;", "”").replace("&hellip;", "…"))
    s = NB_RE.sub("", s)
    return s


def normalize(s: str) -> str:
    """归一化：全半角、空白、大小写，用于去重与匹配"""
    s = unicodedata.normalize("NFKC", s or "")
    s = WS_RE.sub(" ", s)
    return s.strip().lower()


def clean_text(s: str) -> str:
    s = strip_html(s)
    s = WS_RE.sub(" ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def first_sentence(s: str, max_len: int = 120) -> str:
    """取首句作为降级摘要"""
    s = clean_text(s)
    if not s:
        return ""
    parts = re.split(r"(?<=[。！？!?；;.])\s*", s)
    out = parts[0] if parts else s
    if len(out) < 20 and len(parts) > 1:
        out = out + parts[1]
    return truncate(out, max_len)


def sha(text: str, n: int = 10) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def event_id(week: str, seed: str) -> str:
    return f"evt_{week.replace('-', '')}_{sha(seed, 6)}"


# ---------------- IO ----------------

def read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_json(path: pathlib.Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def log(msg: str) -> None:
    print(f"[{now():%H:%M:%S}] {msg}", flush=True)
