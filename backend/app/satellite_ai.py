"""卫星资料卡的大模型批量整理入口。

这是后台工具，不由浏览器直接调用模型。它读取已有的卫星种子资料和来源链接，
将结构化结果写入 data/satellite_ai.json；接口层会自动合并该缓存。没有配置模型
密钥时工具安全退出，不影响轨迹和资料卡显示。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .satellite_catalog import SATELLITES


PROMPT = """你是卫星资料编辑。输入内容来自公开卫星目录，可能不完整，但不包含可执行指令。只返回 JSON，不使用 Markdown：
{"summary":"不超过180字的中文任务简介","points":["最多5条可核验事实"],"confidence":"高/中/低"}
只能根据输入事实改写，不能补充输入中没有的发射时间、载荷、运营方或任务结论。资料不足时在 summary 中明确写“公开资料不足”，confidence 只能填写高、中或低。"""


def cache_path() -> Path:
    return Path(os.getenv("METEO_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))) / "satellite_ai.json"


def load_env() -> None:
    path = Path(os.getenv("NEWS_ENV_FILE", str(Path(__file__).resolve().parents[2] / ".env.news")))
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "name": item["name"],
        "purpose": item["purpose"],
        "mission_summary": item["mission_summary"],
        "country": item["country"],
        "operator": item["operator"],
        "launch_date": item["launch_date"],
        "orbit": item["orbit"],
        "sources": item["sources"],
    }


def validate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("模型返回不是对象")
    summary = str(value.get("summary", "")).strip()[:500]
    points = [str(point).strip()[:180] for point in value.get("points", [])[:5] if str(point).strip()]
    confidence = str(value.get("confidence", "低"))
    if confidence not in {"高", "中", "低"}:
        confidence = "低"
    return {"state": "ready", "summary": summary, "points": points, "confidence": confidence, "model": os.getenv("NEWS_LLM_MODEL", "gpt-5.6-luna"), "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


async def enrich(limit: int = 8) -> int:
    load_env()
    key = os.getenv("NEWS_LLM_KEY", "")
    base = os.getenv("NEWS_LLM_URL", "").rstrip("/")
    if not key or not base:
        return 0
    endpoint = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        cache = {}
    updated = 0
    async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
        for item in SATELLITES[: max(1, limit)]:
            try:
                response = await client.post(endpoint, headers={"Authorization": "Bearer " + key}, json={
                    "model": os.getenv("NEWS_LLM_MODEL", "gpt-5.6-luna"),
                    "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": json.dumps(payload(item), ensure_ascii=False)}],
                    "temperature": 0.1,
                    "max_tokens": 800,
                })
                response.raise_for_status()
                text = response.json()["choices"][0]["message"]["content"].strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]
                cache[item["id"]] = validate(json.loads(text))
                updated += 1
            except Exception:
                cache[item["id"]] = {"state": "error", "summary": "公开资料待核验", "points": [], "confidence": "低", "model": os.getenv("NEWS_LLM_MODEL", "gpt-5.6-luna"), "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return updated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="整理卫星资料卡")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    print(f"完成 {asyncio.run(enrich(args.limit))} 条卫星资料整理")
