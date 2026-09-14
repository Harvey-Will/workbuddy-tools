from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .editions import AppPaths, make_paths
from .models import TokenEvent, color_for_model


def _parse_ts(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = int(value)
        # seconds vs ms
        if v < 10_000_000_000:
            v *= 1000
        return v
    if isinstance(value, str):
        try:
            v = int(float(value))
            if v < 10_000_000_000:
                v *= 1000
            return v
        except ValueError:
            return None
    return None


def _extract_usage(obj: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict):
        return None
    usage = obj.get("usage")
    if isinstance(usage, dict) and any(k in usage for k in ("input_tokens", "total_tokens", "output_tokens")):
        return usage
    msg = obj.get("message")
    if isinstance(msg, dict):
        u = msg.get("usage")
        if isinstance(u, dict):
            return u
    return None


def _extract_model(obj: Any) -> str:
    if not isinstance(obj, dict):
        return "unknown"
    pd = obj.get("providerData")
    if isinstance(pd, dict):
        for k in ("requestModelName", "model", "requestModelId"):
            v = pd.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        raw = pd.get("rawUsage")
        if isinstance(raw, dict):
            for k in ("model", "model_id"):
                if isinstance(raw.get(k), str) and raw[k].strip():
                    return raw[k].strip()
    for k in ("model", "modelName"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "unknown"


def _int(v: Any) -> int:
    try:
        if v is None:
            return 0
        return int(v)
    except (TypeError, ValueError):
        return 0


def iter_token_events(paths: AppPaths) -> Iterable[TokenEvent]:
    if not paths.projects_dir.exists():
        return
    for jsonl in paths.projects_dir.rglob("*.jsonl"):
        # skip subagents optional? include them for accuracy
        session_id = jsonl.parent.name if jsonl.parent.name != "subagents" else jsonl.parent.parent.name
        if jsonl.parent.name == "subagents":
            session_id = jsonl.parent.parent.name
        else:
            session_id = jsonl.stem
        try:
            with open(jsonl, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    usage = _extract_usage(obj)
                    if not usage:
                        continue
                    ts = _parse_ts(obj.get("timestamp")) or _parse_ts(obj.get("ts"))
                    if ts is None:
                        continue
                    inp = _int(usage.get("input_tokens") or usage.get("prompt_tokens"))
                    out = _int(usage.get("output_tokens") or usage.get("completion_tokens"))
                    cache = _int(
                        usage.get("cache_read_input_tokens")
                        or usage.get("cache_read_tokens")
                        or usage.get("cached_tokens")
                    )
                    total = _int(usage.get("total_tokens"))
                    if total <= 0:
                        total = inp + out
                    if total <= 0 and inp <= 0 and out <= 0:
                        continue
                    yield TokenEvent(
                        ts_ms=ts,
                        model=_extract_model(obj),
                        input_tokens=inp,
                        output_tokens=out,
                        cache_read=cache,
                        total_tokens=total,
                        session_id=session_id,
                        edition=paths.edition,
                    )
        except OSError:
            continue


def _range_bounds(range_key: str, date_from: Optional[str], date_to: Optional[str]) -> Tuple[int, int]:
    now = datetime.now(timezone.utc)
    if range_key == "today":
        local = datetime.now().astimezone()
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        end = local
    elif range_key == "24h":
        start = datetime.now().astimezone() - timedelta(hours=24)
        end = datetime.now().astimezone()
    elif range_key == "7d":
        start = datetime.now().astimezone() - timedelta(days=7)
        end = datetime.now().astimezone()
    elif range_key == "30d":
        start = datetime.now().astimezone() - timedelta(days=30)
        end = datetime.now().astimezone()
    elif range_key == "90d":
        start = datetime.now().astimezone() - timedelta(days=90)
        end = datetime.now().astimezone()
    elif range_key == "custom" and date_from and date_to:
        def parse_one(s: str) -> datetime:
            if len(s) == 10:
                return datetime.fromisoformat(s).astimezone()
            # ms
            return datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc).astimezone()

        start = parse_one(date_from)
        end = parse_one(date_to)
    else:
        start = datetime.now().astimezone() - timedelta(days=7)
        end = datetime.now().astimezone()
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def summarize_tokens(
    edition: str,
    range_key: str = "7d",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    paths = make_paths(edition)
    start_ms, end_ms = _range_bounds(range_key, date_from, date_to)

    totals = {"input": 0, "output": 0, "cache_read": 0, "total": 0}
    by_model_acc: Dict[str, Dict[str, int]] = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "total": 0})
    by_day_model: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "total": 0})
    )
    event_count = 0

    for ev in iter_token_events(paths):
        if ev.ts_ms < start_ms or ev.ts_ms > end_ms:
            continue
        event_count += 1
        totals["input"] += ev.input_tokens
        totals["output"] += ev.output_tokens
        totals["cache_read"] += ev.cache_read
        totals["total"] += ev.total_tokens
        m = ev.model or "unknown"
        acc = by_model_acc[m]
        acc["input"] += ev.input_tokens
        acc["output"] += ev.output_tokens
        acc["cache_read"] += ev.cache_read
        acc["total"] += ev.total_tokens
        day = datetime.fromtimestamp(ev.ts_ms / 1000).astimezone().strftime("%Y-%m-%d")
        dacc = by_day_model[day][m]
        dacc["input"] += ev.input_tokens
        dacc["output"] += ev.output_tokens
        dacc["cache_read"] += ev.cache_read
        dacc["total"] += ev.total_tokens

    cache_hit_rate = 0.0
    # cache hit rate approx: cache_read / (input) when input > 0
    if totals["input"] > 0:
        cache_hit_rate = round(min(1.0, totals["cache_read"] / totals["input"]), 4)
    elif totals["total"] > 0:
        cache_hit_rate = 0.0

    by_model = []
    for model, acc in sorted(by_model_acc.items(), key=lambda x: -x[1]["total"]):
        by_model.append(
            {
                "model": model,
                "color": color_for_model(model),
                **acc,
                "cache_hit_rate": round(min(1.0, acc["cache_read"] / acc["input"]), 4) if acc["input"] else 0.0,
            }
        )

    by_day = []
    for day in sorted(by_day_model.keys()):
        models = []
        for model, acc in sorted(by_day_model[day].items(), key=lambda x: -x[1]["total"]):
            models.append({"model": model, "color": color_for_model(model), **acc})
        day_total = sum(m["total"] for m in models)
        by_day.append({"date": day, "total": day_total, "by_model": models})

    return {
        "edition": paths.edition,
        "range": {
            "key": range_key,
            "from": datetime.fromtimestamp(start_ms / 1000).astimezone().isoformat(),
            "to": datetime.fromtimestamp(end_ms / 1000).astimezone().isoformat(),
            "from_ms": start_ms,
            "to_ms": end_ms,
        },
        "totals": {**totals, "cache_hit_rate": cache_hit_rate, "events": event_count},
        "by_model": by_model,
        "by_day": by_day,
    }
