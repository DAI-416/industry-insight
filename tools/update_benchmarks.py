"""抓取主流大模型跑分，写入 config/models.yml。

数据源：Artificial Analysis 排行榜（页面内嵌 initialModels JSON）
  https://artificialanalysis.ai/leaderboards/models

设计原则：
  · 只保留关注厂商的模型，不做全量落库（体积与噪声）
  · 抓取失败时**保留旧文件**，页面会显示「数据截至 X」，不会出现空白或假数据
  · 明确记录数据来源与时间戳，避免读者误以为实时
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys
import urllib.request

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "config" / "models.yml"
URL = "https://artificialanalysis.ai/leaderboards/models"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 关注的厂商：显示名 → 匹配规则（大小写不敏感，含任一关键字即命中）
VENDORS = {
    "OpenAI": ["openai"],
    "Anthropic": ["anthropic"],
    "Google": ["google", "deepmind"],
    "Meta": ["meta"],
    "xAI": ["xai"],
    "Mistral": ["mistral"],
    "阿里 Qwen": ["alibaba", "qwen"],
    "月之暗面 Kimi": ["moonshot", "kimi"],
    "智谱 GLM": ["zhipu", "z ai", "glm"],
    "深度求索 DeepSeek": ["deepseek"],
    "字节豆包": ["bytedance", "doubao", "seed"],
    "腾讯混元": ["tencent", "hunyuan"],
    "百度文心": ["baidu", "ernie"],
    "MiniMax": ["minimax"],
}

# 关注的评测项（键名与页面 scores 字段一致）
BENCHES = {
    "intelligenceIndex": "综合智能指数",
    "gpqa-diamond": "GPQA Diamond",
    "humanitys-last-exam": "Humanity's Last Exam",
    "terminalbench-hard": "TerminalBench Hard",
    "tau2-bench": "τ²-Bench",
    "ifbench": "IFBench",
    "artificial-analysis-long-context-reasoning": "长上下文推理",
    "critpt": "CritPt",
}


def fetch_html() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def extract_models(html: str) -> list[dict]:
    """从 RSC 流式 payload 中抠出 initialModels 数组。"""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    blob = "".join(chunks)
    try:
        blob = blob.encode().decode("unicode_escape", "ignore")
    except UnicodeDecodeError:
        pass

    key = '"initialModels":['
    start = blob.find(key)
    if start < 0:
        return []
    arr_start = start + len(key) - 1

    depth, in_str, esc = 0, False, False
    for i in range(arr_start, len(blob)):
        ch = blob[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                raw = blob[arr_start:i + 1]
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return []
    return []


def vendor_of(model: dict) -> str | None:
    creator = str(model.get("modelCreatorName") or "").lower()
    for vendor, keys in VENDORS.items():
        if any(k in creator for k in keys):
            return vendor
    return None


def build(models: list[dict]) -> dict:
    rows = []
    for m in models:
        vendor = vendor_of(m)
        if not vendor:
            continue
        idx = m.get("intelligenceIndex")
        if idx is None:
            continue
        scores = m.get("scores") or {}
        bench = {}
        for k, label in BENCHES.items():
            v = idx if k == "intelligenceIndex" else scores.get(k)
            if isinstance(v, (int, float)):
                bench[label] = round(float(v) * (100 if v <= 1 else 1), 1)
        rows.append({
            "name": m.get("name") or m.get("shortName") or m.get("slug"),
            "vendor": vendor,
            "index": round(float(idx), 1),
            "context_k": round((m.get("contextWindowTokens") or 0) / 1000),
            "price_in": m.get("price1mInputTokens"),
            "price_out": m.get("price1mOutputTokens"),
            "bench": bench,
        })

    # 同一型号常有多个推理档位（Max / Xhigh / High），按基础名去重取最高分
    def base_name(name: str) -> str:
        return re.sub(r"\s*\([^)]*\)\s*$", "", name or "").strip()

    best: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["vendor"], base_name(r["name"]))
        if key not in best or r["index"] > best[key]["index"]:
            r["name"] = key[1]
            best[key] = r

    # 每个厂商最多 3 个，避免同一家刷屏
    by_vendor: dict[str, list[dict]] = {}
    for r in best.values():
        by_vendor.setdefault(r["vendor"], []).append(r)
    trimmed = []
    for vendor, items in by_vendor.items():
        items.sort(key=lambda x: -x["index"])
        trimmed.extend(items[:3])
    trimmed.sort(key=lambda x: -x["index"])

    return {
        "source": "Artificial Analysis 排行榜（intelligenceIndex）",
        "source_url": URL,
        "as_of": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "note": "第三方综合评测，与厂商自报跑分口径不同，仅作横向参考",
        "vendors": list(VENDORS.keys()),
        "models": trimmed,
    }


def main() -> int:
    try:
        html = fetch_html()
        models = extract_models(html)
        if not models:
            print("抓取失败：未找到 initialModels 数据")
            return 1
        data = build(models)
        if not data["models"]:
            print("抓取失败：命中厂商为 0，可能是站点结构变更")
            return 1
        OUT.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False, width=140),
                       encoding="utf-8")
        print(f"写入 {OUT}：{len(data['models'])} 个型号，覆盖 "
              f"{len({m['vendor'] for m in data['models']})} 家厂商")
        for m in data["models"][:6]:
            print(f"  {m['index']:>5}  {m['vendor']:<14}{m['name']}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"抓取异常：{type(e).__name__}: {e}")
        if OUT.exists():
            print("保留既有 config/models.yml 不变")
        else:
            print("且当前无历史文件，页面将显示「数据待更新」")
        return 1


if __name__ == "__main__":
    sys.exit(main())
