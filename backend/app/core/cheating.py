"""Cheating score (0-100) from proctoring events: points per event, capped per event type."""
from collections import Counter
from typing import Iterable

WEIGHTS = {  # type: (points per event, cap for that type)
    "tab_switch": (5, 30), "window_blur": (2, 10), "fullscreen_exit": (5, 25),
    "face_lost": (3, 20), "multi_face": (10, 40), "gaze_away": (2, 15),
    "voice": (2, 15), "phone": (15, 45), "identity_mismatch": (20, 50),
    "camera_blocked": (10, 30), "copy_paste": (3, 15), "blocked_shortcut": (3, 15),
    "session_replaced": (10, 20), "ip_change": (10, 20),
}
ALLOWED_EVENT_TYPES = set(WEIGHTS) | {"offline", "online", "camera_ready", "ai_unavailable", "note"}


def cheating_score(event_types: Iterable[str]) -> int:
    total = 0
    for t, n in Counter(event_types).items():
        if t in WEIGHTS:
            w, cap = WEIGHTS[t]
            total += min(n * w, cap)
    return min(100, total)


def level(score: int) -> str:
    return "low" if score < 20 else "medium" if score < 50 else "high"
