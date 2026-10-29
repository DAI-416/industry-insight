"""P6 摘要生成 + P7 反幻觉校验。

约束（对应 PRD §5.3）：
  1. 无原文 URL 不发布
  2. 摘要中的数字必须能在原文定位
  3. 校验不通过则回退为原文首句（安全降级），并标记 audit
"""
from __future__ import annotations

import concurrent.futures as cf
import re

from . import gemini, util

SUMMARY_MAX = 140

PROMPT = """请用一句中文概括下面这条资讯的核心事实，不超过 80 字。

严格规则：
1. 只能用原文中出现的信息，不得添加背景、不得推断原因、不得补充原文没有的数字
2. 不要写"据悉""业内认为"这类填充词
3. 不要给评价，只陈述事实
4. 若原文信息不足以概括，直接输出原文第一句

标题：{title}
正文：{body}

摘要："""

# 只校验「有风险的数字」：多位数、小数、百分数。个位数字（1-9）容错，
# 避免误杀"3 家企业"这类原文用汉字表述、摘要用阿拉伯数字的正常改写。
RISKY_NUM = re.compile(r"\d{2,}(?:\.\d+)?%?|\d+\.\d+%?|\d+%")
NUM_STRIP = re.compile(r"[,，\s]")


def _risky_numbers(text: str) -> set[str]:
    return {NUM_STRIP.sub("", m.group(0)) for m in RISKY_NUM.finditer(text or "")}


def verify(summary: str, source_text: str, url: str) -> tuple[bool, list[str]]:
    """返回 (是否通过, 可疑数字列表)"""
    if not url or not url.startswith("http"):
        return False, ["无原文链接"]
    if not summary or len(summary.strip()) < 8:
        return False, ["摘要过短"]
    src = NUM_STRIP.sub("", source_text or "")
    missing = [n for n in _risky_numbers(summary) if n not in src]
    return (not missing), missing


def _body_for_summary(it: dict) -> str:
    """摘要取句的正文：优先正文，其次摘要，最后标题。

    若正文以标题开头（常见于资讯站），先剥掉重复标题，避免摘要复读标题。
    """
    title = (it.get("title") or "").strip()
    for field in ("content", "summary"):
        body = (it.get(field) or "").strip()
        if len(body) < 30:
            continue
        if title and body.startswith(title):
            body = body[len(title):].lstrip("　 ：:，,。|｜-—【】[]()（）")
        if len(body) >= 20:
            return body
    return title or (it.get("summary") or "")


def _summarize_one(it: dict, cfg: dict, use_llm: bool) -> dict:
    source_text = f"{it['title']} {it.get('summary', '')} {it.get('content', '')}"
    body = _body_for_summary(it)
    raw_summary = None
    method = "first_sentence"

    if use_llm and gemini.available(cfg) and int(it.get("importance_score", 0)) >= 40:
        prompt = PROMPT.format(
            title=it["title"],
            body=(it.get("content") or it.get("summary") or "")[:1500],
        )
        out = gemini.generate(prompt, cfg, purpose="summarize")
        if out:
            cleaned = util.clean_text(out).strip().strip("「」\"' ")
            cleaned = re.sub(r"^(摘要[:：])", "", cleaned).strip()
            if cleaned:
                raw_summary, method = cleaned, "llm"

    if not raw_summary:
        raw_summary = util.first_sentence(body, SUMMARY_MAX)

    it["ai_summary_raw"] = raw_summary
    ok, issues = verify(raw_summary, source_text, it.get("url", ""))

    if ok:
        it["ai_summary"] = util.truncate(raw_summary, SUMMARY_MAX)
        it["summary_method"] = method
        it["audit"] = {"pass": True, "issues": []}
    else:
        # 安全降级：回到原文首句，它必然不引入原文之外的信息
        fallback = util.first_sentence(body, SUMMARY_MAX)
        ok2, issues2 = verify(fallback, source_text, it.get("url", ""))
        it["ai_summary"] = fallback if ok2 else util.truncate(it.get("title", ""), SUMMARY_MAX)
        it["summary_method"] = "fallback"
        it["audit"] = {"pass": False, "issues": issues, "downgraded": True}
        if not ok2:
            it["status"] = "pending_review"
            it["audit"]["issues"] = issues2 or issues
    return it


def run(items: list[dict]) -> tuple[list[dict], dict]:
    cfg = util.load_llm()
    use_llm = gemini.available(cfg)
    util.log(f"P6/P7 摘要与校验：{'Gemini' if use_llm else '首句降级模式'}，共 {len(items)} 条")

    workers = int(cfg.get("params", {}).get("concurrency", 3)) if use_llm else 8
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        items = list(ex.map(lambda it: _summarize_one(it, cfg, use_llm), items))

    stat = {"llm": 0, "fallback": 0, "first_sentence": 0, "pending_review": 0, "downgraded": 0}
    for it in items:
        stat[it.get("summary_method", "first_sentence")] = stat.get(it.get("summary_method", "first_sentence"), 0) + 1
        if it.get("status") == "pending_review":
            stat["pending_review"] += 1
        if it.get("audit", {}).get("downgraded"):
            stat["downgraded"] += 1
    util.log(f"P7 完成：{stat}")
    return items, stat
