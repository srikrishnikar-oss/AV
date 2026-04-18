from __future__ import annotations

DEGRADED_SPEED_LIMIT = 30.0
MAX_OUTAGE_SECONDS = 90.0
MIN_SIGNAL_THRESHOLD = -92.0
PNR_LOOKAHEAD_SEGMENTS = 2
SIGNAL_RECOVERY_POLL_SECONDS = 5.0

APPLICATION_PROFILES: dict[str, dict[str, float]] = {
    "Navigation": {
        "travel_weight": 0.4,
        "risk_weight": 0.22,
        "signal_weight": 0.23,
        "bandwidth_weight": 0.15,
    },
    "Telematics": {
        "travel_weight": 0.16,
        "risk_weight": 0.3,
        "signal_weight": 0.28,
        "bandwidth_weight": 0.26,
    },
    "Ride-hail": {
        "travel_weight": 0.62,
        "risk_weight": 0.14,
        "signal_weight": 0.14,
        "bandwidth_weight": 0.1,
    },
    "OTA Update": {
        "travel_weight": 0.08,
        "risk_weight": 0.24,
        "signal_weight": 0.3,
        "bandwidth_weight": 0.38,
    },
}

DEGRADATION_THRESHOLDS = {
    "FULL_AUTONOMY": -75.0,
    "REDUCED_SPEED": -85.0,
    "SUPERVISED_MODE": -95.0,
}
