"""Scoring, including negative marking, fill-in-the-blank matching and topic breakdown."""
import re
from typing import Any, Dict, List, Optional


def normalize_text(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s).strip()).casefold()


def _num_eq(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return False


def is_answered(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def check_answer(qtype: str, correct: Any, value: Any) -> Optional[bool]:
    """True/False for right/wrong, None when unanswered."""
    if not is_answered(value):
        return None
    if qtype in ("mcq", "tf"):
        try:
            return int(value) == int(correct)
        except (TypeError, ValueError):
            return False
    accepted = correct if isinstance(correct, list) else [correct]
    v = normalize_text(value)
    return any(v == normalize_text(a) or _num_eq(v, str(a).strip()) for a in accepted)


def topics_of(q: Dict) -> List[str]:
    tags = [t for t in (q.get("tags") or []) if t]
    if tags:
        return tags
    return [q.get("subject") or "General"]


def score_attempt(questions: List[Dict], answers: Dict[str, Any], negative_mark: float = 0.0) -> Dict:
    """questions: dicts with id, qtype, correct, marks, tags, subject, section_id.
    negative_mark is the penalty as a FRACTION of the question's marks (0.25 => -0.25 for a 1-mark question).
    A question with several tags counts under each tag in the topic breakdown."""
    correct = wrong = unanswered = total = 0
    raw = 0.0
    max_score = 0.0
    per_q: Dict[str, Dict] = {}
    by_topic: Dict[str, Dict] = {}
    by_section: Dict[str, Dict] = {}
    for q in questions:
        qid = str(q["id"])
        marks = float(q.get("marks") or 1)
        max_score += marks
        total += 1
        res = check_answer(q["qtype"], q["correct"], answers.get(qid))
        if res is None:
            status, awarded = "unanswered", 0.0
            unanswered += 1
        elif res:
            status, awarded = "correct", marks
            correct += 1
        else:
            status, awarded = "wrong", -marks * float(negative_mark or 0)
            wrong += 1
        raw += awarded
        per_q[qid] = {"status": status, "awarded": round(awarded, 4)}
        for t in topics_of(q):
            b = by_topic.setdefault(t, {"total": 0, "correct": 0, "wrong": 0, "score": 0.0, "max": 0.0})
            b["total"] += 1
            b["correct"] += status == "correct"
            b["wrong"] += status == "wrong"
            b["score"] += awarded
            b["max"] += marks
        s = by_section.setdefault(str(q.get("section_id")), {"total": 0, "correct": 0, "score": 0.0, "max": 0.0})
        s["total"] += 1
        s["correct"] += status == "correct"
        s["score"] += awarded
        s["max"] += marks
    score = max(0.0, raw)
    percent = (score / max_score * 100.0) if max_score else 0.0
    for d in list(by_topic.values()) + list(by_section.values()):
        d["score"] = round(d["score"], 4)
        d["percent"] = round(max(0.0, d["score"]) / d["max"] * 100, 2) if d["max"] else 0.0
    return {"score": round(score, 4), "max_score": round(max_score, 4), "percent": round(percent, 2),
            "correct": correct, "wrong": wrong, "unanswered": unanswered, "total": total,
            "per_question": per_q, "by_topic": by_topic, "by_section": by_section}
