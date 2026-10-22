"""Pure timing logic: offline credit and sequential, individually-timed sections.

Section state (stored as JSON on the attempt):
{"timed": bool, "order": ["12","13"], "sections": {"12": {"status": "pending|active|finished",
 "duration": minutes|None, "deadline": iso|None}}}
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional


def iso(dt: Optional[datetime]) -> Optional[str]:
    return None if dt is None else dt.replace(microsecond=0).isoformat() + "Z"


def parse(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.fromisoformat(s.rstrip("Z"))


def offline_credit(claimed_seconds: float, gap_seconds: float, cap_remaining: float, slack: float = 15.0) -> int:
    """Time we are willing to give back after a connection drop.
    The client CLAIMS how long it was offline, but a student could fake that, so we never credit more than
    (a) what the client claims, (b) the real gap the server observed between its last contact and now
    (minus a little slack for the heartbeat interval), and (c) what is left of the per-attempt cap."""
    allowed = min(float(claimed_seconds or 0), float(gap_seconds or 0) - slack, float(cap_remaining or 0))
    return max(0, int(allowed))


def new_state(sections: List[Dict]) -> Dict:
    """sections: [{id, duration_min}] in order."""
    timed = any(s.get("duration_min") for s in sections)
    return {"timed": timed, "order": [str(s["id"]) for s in sections],
            "sections": {str(s["id"]): {"status": "pending", "duration": s.get("duration_min"), "deadline": None}
                         for s in sections}}


def advance(state: Dict, now: datetime) -> Dict:
    """Lazily close sections whose own timer ran out."""
    for sec in state["sections"].values():
        if sec["status"] == "active" and sec["deadline"] and parse(sec["deadline"]) <= now:
            sec["status"] = "finished"
    return state


def active_section(state: Dict) -> Optional[str]:
    for sid in state["order"]:
        if state["sections"][sid]["status"] == "active":
            return sid
    return None


def can_start(state: Dict, sid: str) -> Optional[str]:
    """None when allowed, else a human-readable reason."""
    sid = str(sid)
    if sid not in state["sections"]:
        return "Unknown section"
    if state["sections"][sid]["status"] != "pending":
        return "Section already started or finished"
    if active_section(state):
        return "Finish the current section first"
    for prev in state["order"]:
        if prev == sid:
            break
        if state["sections"][prev]["status"] != "finished":
            return "Sections must be taken in order"
    return None


def start(state: Dict, sid: str, now: datetime, global_expiry: datetime) -> Dict:
    sec = state["sections"][str(sid)]
    sec["status"] = "active"
    dl = global_expiry
    if sec["duration"]:
        dl = min(now + timedelta(minutes=sec["duration"]), global_expiry)
    sec["deadline"] = iso(dl)
    return state


def finish(state: Dict, sid: str) -> Dict:
    state["sections"][str(sid)]["status"] = "finished"
    return state


def shift_deadlines(state: Dict, seconds: int) -> Dict:
    for sec in state["sections"].values():
        if sec["status"] == "active" and sec["deadline"]:
            sec["deadline"] = iso(parse(sec["deadline"]) + timedelta(seconds=seconds))
    return state


def answerable(state: Dict, sid: str) -> bool:
    """May an answer be saved for a question in section `sid` right now?"""
    if not state.get("timed"):
        return True
    return state["sections"].get(str(sid), {}).get("status") == "active"
