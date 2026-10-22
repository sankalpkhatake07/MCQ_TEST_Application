"""Exam insights and item analysis."""
import statistics
from typing import Dict, List


def distribution(percents: List[float], bins: int = 10) -> List[Dict]:
    width = 100 / bins
    counts = [0] * bins
    for p in percents:
        i = min(bins - 1, max(0, int(p // width)))
        counts[i] += 1
    return [{"label": f"{int(i * width)}-{int((i + 1) * width)}", "count": c} for i, c in enumerate(counts)]


def insights(rows: List[Dict], pass_percent: float) -> Dict:
    """rows: [{score, percent, max_score, seconds}] for submitted real attempts."""
    if not rows:
        return {"count": 0, "highest": 0, "lowest": 0, "average": 0, "median": 0, "pass_rate": 0,
                "avg_time_min": 0, "distribution": distribution([])}
    pcts = [r["percent"] for r in rows]
    scores = [r["score"] for r in rows]
    return {
        "count": len(rows), "highest": max(scores), "lowest": min(scores),
        "average": round(statistics.mean(scores), 2), "median": round(statistics.median(scores), 2),
        "avg_percent": round(statistics.mean(pcts), 2),
        "pass_rate": round(100 * sum(1 for p in pcts if p >= pass_percent) / len(pcts), 1),
        "avg_time_min": round(statistics.mean([r.get("seconds", 0) for r in rows]) / 60, 1),
        "distribution": distribution(pcts),
    }


def difficulty_label(p: float) -> str:
    return "easy" if p >= 0.8 else "hard" if p < 0.35 else "medium"


def item_analysis(questions: List[Dict], attempts: List[Dict]) -> List[Dict]:
    """questions: [{id, text, difficulty}], attempts: [{score, per_question:{qid:{status}}, times:{qid:sec}}]
    p = share answering correctly; discrimination = p(top 27%) - p(bottom 27%)."""
    n = len(attempts)
    ordered = sorted(attempts, key=lambda a: a["score"], reverse=True)
    k = max(1, round(n * 0.27)) if n else 0
    top, bottom = ordered[:k], ordered[-k:] if k else []
    out = []
    for q in questions:
        qid = str(q["id"])

        def share(group):
            seen = [a for a in group if qid in a["per_question"]]
            return (sum(1 for a in seen if a["per_question"][qid]["status"] == "correct") / len(seen)) if seen else 0.0

        seen_all = [a for a in attempts if qid in a["per_question"]]
        correct = sum(1 for a in seen_all if a["per_question"][qid]["status"] == "correct")
        wrong = sum(1 for a in seen_all if a["per_question"][qid]["status"] == "wrong")
        skipped = sum(1 for a in seen_all if a["per_question"][qid]["status"] == "unanswered")
        p = correct / len(seen_all) if seen_all else 0.0
        times = [a["times"].get(qid, 0) for a in seen_all if a.get("times")]
        disc = round(share(top) - share(bottom), 2) if n >= 4 else None
        weak = bool(seen_all) and (disc is not None and disc < 0.1 or p < 0.2)
        out.append({"question_id": q["id"], "text": q["text"], "labelled": q.get("difficulty"),
                    "attempts": len(seen_all), "correct": correct, "wrong": wrong, "skipped": skipped,
                    "percent_correct": round(p * 100, 1), "observed_difficulty": difficulty_label(p) if seen_all else None,
                    "discrimination": disc, "avg_time_sec": round(sum(times) / len(times), 1) if times else 0,
                    "weak": weak})
    return out
