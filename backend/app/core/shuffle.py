"""Per-attempt question selection + shuffling (deterministic from a stored seed)."""
import random
from typing import Dict, List


def build_layout(sections: List[Dict], questions: Dict[int, Dict], seed: int,
                 shuffle_questions: bool, shuffle_options: bool) -> Dict:
    """sections: [{id, pick_count, qids}]  questions: {qid: {qtype, choices}}
    Returns {"sections":[{"id","qids"}], "perms":{qid:[original option indexes in display order]}}"""
    rng = random.Random(seed)
    out_sections, perms = [], {}
    for sec in sections:
        pool = list(sec["qids"])
        pick = sec.get("pick_count")
        if pick and 0 < pick < len(pool):
            pool = rng.sample(pool, pick)
        if shuffle_questions:
            rng.shuffle(pool)
        out_sections.append({"id": sec["id"], "qids": pool})
        for qid in pool:
            q = questions[qid]
            order = list(range(len(q.get("choices") or [])))
            if shuffle_options and q["qtype"] == "mcq":
                rng.shuffle(order)
            perms[str(qid)] = order
    return {"sections": out_sections, "perms": perms}


def all_qids(layout: Dict) -> List[int]:
    return [q for s in layout["sections"] for q in s["qids"]]
