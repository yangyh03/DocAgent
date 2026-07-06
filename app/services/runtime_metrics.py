from __future__ import annotations

from typing import Any

from app.schemas import RuntimeMetricEvent, RuntimeMetrics


def empty_runtime_metrics() -> dict[str, Any]:
    return RuntimeMetrics().model_dump()


def add_runtime_event(metrics: dict[str, Any] | RuntimeMetrics | None, event: dict[str, Any]) -> dict[str, Any]:
    """追加一次模型相关事件，并重新计算汇总字段。"""
    events = _events_from_metrics(metrics)
    events.append(RuntimeMetricEvent(**event).model_dump())
    return build_runtime_metrics(events).model_dump()


def merge_runtime_metrics(items: list[dict[str, Any] | RuntimeMetrics | None]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for item in items:
        events.extend(_events_from_metrics(item))
    return build_runtime_metrics(events).model_dump()


def build_runtime_metrics(events: list[dict[str, Any]]) -> RuntimeMetrics:
    ''' 统计总调用次数、失败次数、fallback 次数、每个阶段的耗时等 '''
    normalized_events = [RuntimeMetricEvent(**event) for event in events]
    by_stage: dict[str, dict[str, Any]] = {}
    for event in normalized_events:
        stage = event.stage or "unknown"
        stage_summary = by_stage.setdefault(
            stage,
            {
                "event_count": 0,
                "model_call_count": 0,
                "success_count": 0,
                "failed_count": 0,
                "fallback_count": 0,
                "total_duration_ms": 0,
                "input_items": 0,
                "output_items": 0,
            },
        )
        stage_summary["event_count"] += 1
        if event.status in {"success", "partial_success", "failed"}:
            stage_summary["model_call_count"] += 1
        if event.status == "success":
            stage_summary["success_count"] += 1
        if event.status == "failed":
            stage_summary["failed_count"] += 1
        if event.fallback_used:
            stage_summary["fallback_count"] += 1
        stage_summary["total_duration_ms"] += event.duration_ms
        stage_summary["input_items"] += event.input_items
        stage_summary["output_items"] += event.output_items

    return RuntimeMetrics(
        model_call_count=sum(1 for event in normalized_events if event.status in {"success", "partial_success", "failed"}),
        success_count=sum(1 for event in normalized_events if event.status == "success"),
        failed_count=sum(1 for event in normalized_events if event.status == "failed"),
        fallback_count=sum(1 for event in normalized_events if event.fallback_used),
        total_duration_ms=sum(event.duration_ms for event in normalized_events),
        by_stage=by_stage,
        events=normalized_events,
    )


def _events_from_metrics(metrics: dict[str, Any] | RuntimeMetrics | None) -> list[dict[str, Any]]:
    if metrics is None:
        return []
    if isinstance(metrics, RuntimeMetrics):
        return [event.model_dump() for event in metrics.events]
    raw_events = metrics.get("events", []) if isinstance(metrics, dict) else []
    return [dict(event) for event in raw_events if isinstance(event, dict)]
