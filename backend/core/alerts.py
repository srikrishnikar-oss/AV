from __future__ import annotations

from typing import Any


def build_alert(event_type: str, severity: str, message: str, **payload: Any) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "severity": severity,
        "message": message,
        "payload": payload,
    }


def banners_from_fallback_status(status: dict[str, Any]) -> list[dict[str, Any]]:
    banners: list[dict[str, Any]] = []
    last_event = status.get("last_event")
    if last_event:
        banners.append(last_event)

    if status.get("active_degradation_level") == "PULL_OVER" and status.get("dead_zone_timer_s", 0) > 0:
        banners.append(
            build_alert(
                "DEAD_ZONE_TIMEOUT",
                "critical",
                "Vehicle is operating without connectivity and may need to halt soon.",
                dead_zone_timer_s=status.get("dead_zone_timer_s", 0),
            )
        )

    return banners
