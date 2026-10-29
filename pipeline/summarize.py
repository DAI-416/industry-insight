"""P6 摘要生成 + P7 反幻觉校验。

性能设计：摘要同样批量（一次 BATCH 条），只对重要度 ≥ 阈值的条目调用模型，
低优先级直接用原文首句——实测可把摘要阶段从数分钟压到数十秒。

约束（对应 PRD §5.3）：
  1. 无原文 URL 不发布
  2. 摘要中的高风险数字（多位数/小数/百分数）必须能在原文定位
  3. 校验不通过 → 回退原文首句（安全降级），并记录 audit
"""
from __future__ import annotations

import re

from . import gemini, util

SUMMARY_MAX = 140
LLM_SCORE_THRESHOLD = 60   # 仅「重要」及以上做模型摘要
BATCH = 5

# 只校验「有风险的数字」：多位数、小数、百分数。个位数字（1-9）容错，
# 避免误杀"3 家企业"这类原文用汉字表述、摘要用阿拉伯数字的正常改写。
RISKY_NUM = re.compile(r"\d{2,}(?:\.\d+)?%?|\d+\.\d+%?|\d+%")
NUM_STRIP = re.compile(r"[,，\s]")

PROMPT = """把下面 {n} 条资讯各压缩成一句中文摘要，每条不超过 80 字。

严格规则：
1. 只能用原文出现的信息，不得添加背景、不得推断原因、不得补充原文没有的数字
2. 不要"据悉""业内认为"这类填充词，不要给评价，只陈述事实
3. 原文信息不足时，直接输出该条原文的第一句

{items}

严格输出 JSON，不要解释：
{{"results":[{{"i":1,"summary":"……"}}]}}"""


def _risky_numbers(text: str) -> set[str]:
    return {NUM_STRIP.sub("", m.group(0)) for m in RISKY_NUM.finditer(text or "")}


def verify(summary: str, source_text: str, url: str) -> tuple[bool, list[str]]:
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


def _source_text(it: dict) -> str:
    return f"{it['title']} {it.get('summary', '')} {it.get('content', '')}"


def _build_prompt(batch: list[dict]) -> str:
    lines = []
    for idx, it in enumerate(batch, 1):
        body = (it.get("content") or it.get("summary") or "")[:600].replace("\n", " ")
        lines.append(f'[{idx}] 标题：{it["title"]}\n    正文：{body}')
    return PROMPT.format(n=len(batch), items="\n".join(lines))


def _summarize_batch(batch: list[dict], cfg: dict) -> dict[int, str]:
    raw = gemini.generate(_build_prompt(batch), cfg, purpose="summarize")
    data = gemini.extract_json(raw)
    if not data or "results" not in data:
        return {}
    out: dict[int, str] = {}
    for row in data["results"]:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("i"))
        except (TypeError, ValueError):
            continue
        text = util.clean_text(str(row.get("summary", ""))).strip().strip("「」\"' ")
        text = re.sub(r"^(摘要[:：])", "", text).strip()
        if 1 <= idx <= len(batch) and text:
            out[idx] = text
    return out


def run(items: list[dict]) -> tuple[list[dict], dict]:
    cfg = util.load_llm()
    use_llm = gemini.available(cfg)

    # ① 全部先用原文首句兜底，保证任何情况下都有可用摘要
    for it in items:
        body = _body_for_summary(it)
        it["ai_summary"] = util.truncate(util.first_sentence(body, SUMMARY_MAX), SUMMARY_MAX)
        it["ai_summary_raw"] = it["ai_summary"]
        it["summary_method"] = "first_sentence"
        it["audit"] = {"pass": True, "issues": [], "note": "原文首句，不经模型"}

    # ② 选出需要模型摘要的条目
    targets = [i for i, it in enumerate(items)
               if int(it.get("importance_score", 0)) >= LLM_SCORE_THRESHOLD]
    mode = "Gemini 批量" if use_llm else "首句降级模式"
    util.log(f"P6/P7 摘要与校验：{mode}；需模型摘要 {len(targets)}/{len(items)} 条，批大小 {BATCH}")

    stat = {"llm": 0, "first_sentence": len(items) - len(targets), "fallback": 0,
            "downgraded": 0, "pending_review": 0, "batches": 0}

    if use_llm and targets:
        for start in range(0, len(targets), BATCH):
            if not gemini.available(cfg):
                util.log("  LLM 已熔断，剩余条目保留首句摘要")
                break
            idxs = targets[start:start + BATCH]
            batch = [items[i] for i in idxs]
            got = _summarize_batch(batch, cfg)
            stat["batches"] += 1
            util.log(f"  批次 {stat['batches']}：{len(got)}/{len(batch)} 条生成成功")

            for local_i, text in got.items():
                it = items[idxs[local_i - 1]]
                src = _source_text(it)
                ok, issues = verify(text, src, it.get("url", ""))
                if ok:
                    it["ai_summary"] = util.truncate(text, SUMMARY_MAX)
                    it["ai_summary_raw"] = text
                    it["summary_method"] = "llm"
                    it["audit"] = {"pass": True, "issues": []}
                    stat["llm"] += 1
                else:
                    # 安全降级：模型摘要含原文没有的数字，退回原文首句
                    fallback = util.truncate(util.first_sentence(_body_for_summary(it), SUMMARY_MAX), SUMMARY_MAX)
                    it["ai_summary"] = fallback
                    it["ai_summary_raw"] = text
                    it["summary_method"] = "fallback"
                    it["audit"] = {"pass": False, "issues": issues, "downgraded": True}
                    stat["fallback"] += 1
                    stat["downgraded"] += 1

    # ③ 无源不发布（PRD §5.3 硬约束）
    for it in items:
        if not (it.get("url") or "").startswith("http"):
            it["status"] = "pending_review"
            it["audit"] = {"pass": False, "issues": ["无原文链接"]}
            stat["pending_review"] += 1

    util.log(f"P7 完成：模型 {stat['llm']} / 首句 {stat['first_sentence']} / "
             f"降级 {stat['downgraded']} / 退回待复核 {stat['pending_review']}")
    return items, stat
