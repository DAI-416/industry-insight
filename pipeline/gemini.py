"""Gemini API 客户端（标准库实现）。

无 GEMINI_API_KEY 或预算耗尽时返回 None，由调用方走规则降级。
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.request

from . import util

_LOCK = threading.Lock()
_SPEND = {"cny": 0.0}


def available(cfg: dict) -> bool:
    if not os.environ.get("GEMINI_API_KEY"):
        return False
    limit = float(cfg.get("budget", {}).get("monthly_cny_limit", 100))
    with _LOCK:
        return _SPEND["cny"] < limit


def spend() -> float:
    with _LOCK:
        return round(_SPEND["cny"], 4)


def _record(tokens_in: int, tokens_out: int, cfg: dict) -> None:
    b = cfg.get("budget", {})
    cost = (tokens_in / 1000 * float(b.get("cny_per_1k_input_tokens", 0.001))
            + tokens_out / 1000 * float(b.get("cny_per_1k_output_tokens", 0.004)))
    with _LOCK:
        _SPEND["cny"] += cost


def generate(prompt: str, cfg: dict, purpose: str = "summarize") -> str | None:
    """调用 Gemini 生成文本。失败返回 None（不抛异常）。"""
    if not available(cfg):
        return None
    model = cfg.get("models", {}).get(purpose) or cfg.get("models", {}).get("summarize")
    endpoint = cfg.get("endpoint", "https://generativelanguage.googleapis.com/v1beta/models")
    params = cfg.get("params", {})
    key = os.environ["GEMINI_API_KEY"]

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(params.get("temperature", 0.2)),
            "maxOutputTokens": int(params.get("max_output_tokens", 512)),
        },
    }
    req = urllib.request.Request(
        f"{endpoint}/{model}:generateContent?key={key}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for _ in range(int(params.get("max_retry", 2))):
        try:
            with urllib.request.urlopen(req, timeout=int(params.get("timeout_sec", 30))) as r:
                payload = json.loads(r.read().decode("utf-8"))
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            usage = payload.get("usageMetadata", {})
            _record(int(usage.get("promptTokenCount", 0)),
                    int(usage.get("candidatesTokenCount", 0)), cfg)
            return text.strip()
        except Exception as e:  # noqa: BLE001
            util.log(f"  Gemini 调用失败（{type(e).__name__}），重试中")
            continue
    return None


def extract_json(text: str) -> dict | None:
    """从模型输出里抠出第一段 JSON 对象。"""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(candidate[start:end + 1])
    except json.JSONDecodeError:
        return None
