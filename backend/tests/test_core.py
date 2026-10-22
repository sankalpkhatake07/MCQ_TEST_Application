"""Run with:  python -m unittest discover -s tests -v   (from the backend folder). No third-party test runner needed."""
import io
import json
import unittest
from datetime import datetime, timedelta

from app.core import analytics, cheating, importers, netutil, sanitize, scoring, shuffle, timing


class SanitizeTests(unittest.TestCase):
    def test_strips_scripts_and_handlers(self):
        out = sanitize.sanitize_html('<p onclick="x()">Hi<script>alert(1)</script><b>there</b></p><iframe src="//e"></iframe>')
        self.assertEqual(out, "<p>Hi<b>there</b></p>")

    def test_img_only_from_media(self):
        ok = sanitize.sanitize_html('<img src="/api/media/' + "a" * 32 + '.png" onerror="x()">')
        self.assertIn('src="/api/media/', ok)
        self.assertNotIn("onerror", ok)
        self.assertEqual(sanitize.sanitize_html('<img src="http://evil/x.png">'), "")
        self.assertEqual(sanitize.sanitize_html('<img src="javascript:alert(1)">'), "")

    def test_unclosed_tags_are_closed_and_text_escaped(self):
        self.assertEqual(sanitize.sanitize_html("<b>a < b"), "<b>a &lt; b</b>")

    def test_plain_text_is_escaped_not_interpreted(self):
        self.assertEqual(sanitize.to_rich("if a < b and c > d"), "<p>if a &lt; b and c &gt; d</p>")
        self.assertIn("<code>", sanitize.to_rich("use <code>x</code>"))

    def test_strip_tags(self):
        self.assertEqual(sanitize.strip_tags("<p>One</p><p>Two <b>x</b></p><script>bad()</script>"), "One\nTwo x")


class ScoringTests(unittest.TestCase):
    QS = [
        {"id": 1, "qtype": "mcq", "correct": 1, "marks": 1, "tags": ["A"], "section_id": 10},
        {"id": 2, "qtype": "mcq", "correct": 0, "marks": 2, "tags": ["A", "B"], "section_id": 10},
        {"id": 3, "qtype": "tf", "correct": 1, "marks": 1, "tags": [], "subject": "Math", "section_id": 11},
        {"id": 4, "qtype": "fill", "correct": ["Print", "print()"], "marks": 1, "tags": ["B"], "section_id": 12},
    ]

    def test_negative_marking_is_fraction_of_marks(self):
        r = scoring.score_attempt(self.QS, {"1": 1, "2": 3, "3": 0, "4": "  PRINT "}, 0.25)
        # +1 (q1) -0.5 (q2 wrong, 2 marks) -0.25 (q3 wrong) +1 (q4)
        self.assertEqual(r["score"], 1.25)
        self.assertEqual((r["correct"], r["wrong"], r["unanswered"]), (2, 2, 0))
        self.assertEqual(r["max_score"], 5)

    def test_unanswered_scores_zero_and_total_never_negative(self):
        r = scoring.score_attempt(self.QS, {"1": 0, "2": 1, "3": 0}, 1.0)
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["percent"], 0.0)
        self.assertEqual(r["unanswered"], 1)

    def test_fill_numeric_and_whitespace(self):
        self.assertTrue(scoring.check_answer("fill", ["3.0"], " 3 "))
        self.assertTrue(scoring.check_answer("fill", ["New  York"], "new york"))
        self.assertFalse(scoring.check_answer("fill", ["x"], "y"))
        self.assertIsNone(scoring.check_answer("fill", ["x"], "   "))

    def test_mcq_zero_index_counts_as_answered(self):
        self.assertTrue(scoring.check_answer("mcq", 0, 0))
        self.assertIsNone(scoring.check_answer("mcq", 0, None))

    def test_topic_breakdown_multi_tag(self):
        r = scoring.score_attempt(self.QS, {"1": 1, "2": 0}, 0)
        self.assertEqual(r["by_topic"]["A"]["correct"], 2)
        self.assertEqual(r["by_topic"]["B"]["total"], 2)       # q2 and q4
        self.assertIn("Math", r["by_topic"])                   # untagged falls back to subject
        self.assertEqual(r["by_topic"]["A"]["percent"], 100.0)


class ShuffleTests(unittest.TestCase):
    Q = {i: {"qtype": "mcq", "choices": ["a", "b", "c", "d"]} for i in range(1, 21)}
    S = [{"id": 1, "pick_count": 5, "qids": list(range(1, 11))}, {"id": 2, "pick_count": None, "qids": list(range(11, 21))}]

    def test_deterministic_per_seed_and_varies_between_seeds(self):
        a = shuffle.build_layout(self.S, self.Q, 42, True, True)
        self.assertEqual(a, shuffle.build_layout(self.S, self.Q, 42, True, True))
        self.assertNotEqual(a, shuffle.build_layout(self.S, self.Q, 43, True, True))

    def test_pick_count_and_membership(self):
        a = shuffle.build_layout(self.S, self.Q, 7, True, True)
        self.assertEqual(len(a["sections"][0]["qids"]), 5)
        self.assertTrue(set(a["sections"][0]["qids"]) <= set(range(1, 11)))
        self.assertEqual(len(set(a["sections"][0]["qids"])), 5)
        self.assertEqual(sorted(a["sections"][1]["qids"]), list(range(11, 21)))

    def test_option_permutations_are_permutations(self):
        a = shuffle.build_layout(self.S, self.Q, 9, False, True)
        for perm in a["perms"].values():
            self.assertEqual(sorted(perm), [0, 1, 2, 3])
        self.assertTrue(any(p != [0, 1, 2, 3] for p in a["perms"].values()))

    def test_no_shuffle_keeps_order(self):
        a = shuffle.build_layout([{"id": 1, "pick_count": None, "qids": [3, 1, 2]}], self.Q, 1, False, False)
        self.assertEqual(a["sections"][0]["qids"], [3, 1, 2])
        self.assertEqual(a["perms"]["3"], [0, 1, 2, 3])


class TimingTests(unittest.TestCase):
    def test_offline_credit_never_exceeds_server_observed_gap(self):
        self.assertEqual(timing.offline_credit(500, 100, 600), 85)       # gap 100 - 15s slack
        self.assertEqual(timing.offline_credit(30, 1000, 600), 30)       # claim is the limit
        self.assertEqual(timing.offline_credit(500, 1000, 120), 120)     # per-attempt cap
        self.assertEqual(timing.offline_credit(9999, 10, 600), 0)        # faked outage but we saw them 10s ago
        self.assertEqual(timing.offline_credit(-5, 100, 600), 0)

    def test_sequential_timed_sections(self):
        now = datetime(2026, 1, 1, 10, 0, 0)
        exp = now + timedelta(minutes=60)
        st = timing.new_state([{"id": 1, "duration_min": 10}, {"id": 2, "duration_min": 5}, {"id": 3, "duration_min": None}])
        self.assertTrue(st["timed"])
        self.assertEqual(timing.can_start(st, "2"), "Sections must be taken in order")
        self.assertIsNone(timing.can_start(st, "1"))
        timing.start(st, "1", now, exp)
        self.assertEqual(timing.can_start(st, "2"), "Finish the current section first")
        self.assertFalse(timing.answerable(st, "2"))
        self.assertTrue(timing.answerable(st, "1"))
        timing.advance(st, now + timedelta(minutes=11))                    # section 1 timer ran out
        self.assertEqual(st["sections"]["1"]["status"], "finished")
        self.assertFalse(timing.answerable(st, "1"))
        self.assertIsNone(timing.can_start(st, "2"))

    def test_section_deadline_capped_by_global_expiry_and_shifted_by_credit(self):
        now = datetime(2026, 1, 1, 10, 0, 0)
        st = timing.new_state([{"id": 1, "duration_min": 30}])
        timing.start(st, "1", now, now + timedelta(minutes=10))
        self.assertEqual(timing.parse(st["sections"]["1"]["deadline"]), now + timedelta(minutes=10))
        timing.shift_deadlines(st, 60)
        self.assertEqual(timing.parse(st["sections"]["1"]["deadline"]), now + timedelta(minutes=11))

    def test_untimed_exam_is_free_navigation(self):
        st = timing.new_state([{"id": 1, "duration_min": None}, {"id": 2, "duration_min": None}])
        self.assertFalse(st["timed"])
        self.assertTrue(timing.answerable(st, "2"))


class CheatingTests(unittest.TestCase):
    def test_caps_per_type_and_total(self):
        self.assertEqual(cheating.cheating_score(["tab_switch"] * 3), 15)
        self.assertEqual(cheating.cheating_score(["tab_switch"] * 50), 30)
        self.assertEqual(cheating.cheating_score(["phone"] * 5 + ["identity_mismatch"] * 5 + ["multi_face"] * 9), 100)
        self.assertEqual(cheating.cheating_score(["offline", "online", "unknown"]), 0)

    def test_levels(self):
        self.assertEqual([cheating.level(x) for x in (0, 19, 20, 49, 50, 100)], ["low", "low", "medium", "medium", "high", "high"])


class NetTests(unittest.TestCase):
    def test_rules(self):
        self.assertTrue(netutil.ip_allowed("10.1.2.3", ["10.0.0.0/8"]))
        self.assertFalse(netutil.ip_allowed("11.1.2.3", ["10.0.0.0/8", "192.168.1.5"]))
        self.assertTrue(netutil.ip_allowed("192.168.1.5", ["192.168.1.5"]))
        self.assertTrue(netutil.ip_allowed("anything", []))
        self.assertFalse(netutil.ip_allowed("", ["10.0.0.0/8"]))
        self.assertFalse(netutil.ip_allowed("not-an-ip", ["10.0.0.0/8"]))
        self.assertEqual(netutil.invalid_rules(["10.0.0.0/8", "nope"]), ["nope"])

    def test_forwarded_for_only_when_trusted(self):
        self.assertEqual(netutil.client_ip("1.1.1.1", "9.9.9.9, 2.2.2.2", False), "1.1.1.1")
        self.assertEqual(netutil.client_ip("1.1.1.1", "9.9.9.9, 2.2.2.2", True), "9.9.9.9")


class ImporterTests(unittest.TestCase):
    def test_csv_flexible_columns_and_no_silent_default_answer(self):
        csv_text = ("text,choice0,choice1,choice2,choice3,correct_index,difficulty,tags\n"
                    "What is 1+1?,1,2,11,Error,1,easy,Basics;Math\n"
                    "No answer given,a,b,c,d,,easy,\n"
                    "Letter answer,x,y,z,,C,hard,\n"
                    "Out of range,x,y,,,9,easy,\n")
        items, errors = importers.parse_csv(csv_text, {"subject": "Py"})
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["correct"], 1)
        self.assertEqual(items[0]["tags"], ["Basics", "Math"])
        self.assertEqual(items[0]["subject"], "Py")
        self.assertEqual(items[1]["correct"], 2)
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("missing" in e for e in errors))

    def test_csv_option_letter_columns_and_types(self):
        csv_text = "question,a,b,c,d,answer,type\nPick,1,2,3,4,b,\nSky is blue,,,,,true,tf\nCapital of France,,,,,Paris|paris,fill\n"
        items, errors = importers.parse_csv(csv_text, {})
        self.assertEqual(errors, [])
        self.assertEqual([i["qtype"] for i in items], ["mcq", "tf", "fill"])
        self.assertEqual(items[1]["correct"], 0)
        self.assertEqual(items[2]["correct"], ["Paris", "paris"])

    def test_json_variants(self):
        data = {"questions": [{"text": "Q", "choices": ["a", "b"], "correct_index": 0}, {"question": "T", "options": ["True", "False"], "answer": "False"},
                              {"text": "bad", "choices": ["a"], "correct_index": 0}]}
        items, errors = importers.parse_json(json.dumps(data), {})
        self.assertEqual([i["qtype"] for i in items], ["mcq", "tf"])
        self.assertEqual(items[1]["correct"], 1)
        self.assertEqual(len(errors), 1)

    TEXT = """Q1. What does CPU stand for?
A) Central Process Unit
B) Central Processing Unit
C) Computer Personal Unit
Answer: B
Difficulty: easy
Topic: Hardware
2) Which are loops
in Python?
a. for
b. while and
   do-while
Answer: A
3. True or false: Python is compiled only.
A) True
B) False
Answer: B
Explanation: It is interpreted/compiled to bytecode.
Q4: The capital of India is ____ .
Answer: New Delhi | Delhi
Q5. Unanswerable question
A) one
B) two
"""

    def test_text_blocks(self):
        items, errors = importers.parse_text_blocks(self.TEXT, {})
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0]["correct"], 1)
        self.assertEqual(items[0]["difficulty"], "easy")
        self.assertEqual(items[0]["tags"], ["Hardware"])
        self.assertEqual(items[1]["text"], "Which are loops\nin Python?")
        self.assertEqual(items[1]["choices"][1], "while and do-while")
        self.assertEqual(items[2]["qtype"], "tf")
        self.assertEqual(items[2]["correct"], 1)
        self.assertIn("bytecode", items[2]["explanation"])
        self.assertEqual(items[3]["qtype"], "fill")
        self.assertEqual(items[3]["correct"], ["New Delhi", "Delhi"])
        self.assertEqual(len(errors), 1)
        self.assertIn("Question 5", errors[0])

    def test_docx_roundtrip(self):
        import docx
        d = docx.Document()
        for line in self.TEXT.splitlines():
            d.add_paragraph(line)
        buf = io.BytesIO()
        d.save(buf)
        items, errors = importers.parse_upload("exam.docx", buf.getvalue(), {})
        self.assertEqual(len(items), 4)
        self.assertEqual(len(errors), 1)

    def test_pdf_roundtrip(self):
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        y = 800
        for line in self.TEXT.splitlines():
            c.drawString(50, y, line.strip())
            y -= 16
        c.save()
        items, errors = importers.parse_upload("exam.pdf", buf.getvalue(), {})
        self.assertGreaterEqual(len(items), 3)
        self.assertEqual(items[0]["correct"], 1)

    def test_empty_document_reports_helpful_error(self):
        items, errors = importers.parse_text_blocks("just some prose", {})
        self.assertEqual(items, [])
        self.assertIn("No questions found", errors[0])


class AnalyticsTests(unittest.TestCase):
    def test_insights_and_distribution(self):
        rows = [{"score": s, "percent": s * 10, "seconds": 600} for s in (2, 4, 6, 8, 10)]
        ins = analytics.insights(rows, 40)
        self.assertEqual((ins["highest"], ins["lowest"], ins["average"], ins["median"]), (10, 2, 6, 6))
        self.assertEqual(ins["pass_rate"], 80.0)
        self.assertEqual(sum(b["count"] for b in ins["distribution"]), 5)
        self.assertEqual(ins["distribution"][-1]["count"], 1)   # 100% lands in the last bin
        self.assertEqual(analytics.insights([], 40)["count"], 0)

    def test_item_analysis_flags_bad_question(self):
        def att(score, q1, q2):
            return {"score": score, "per_question": {"1": {"status": q1}, "2": {"status": q2}}, "times": {"1": 10, "2": 20}}
        attempts = [att(9, "correct", "wrong"), att(8, "correct", "wrong"), att(7, "correct", "correct"), att(3, "wrong", "correct"),
                    att(2, "wrong", "correct"), att(1, "wrong", "correct")]
        items = analytics.item_analysis([{"id": 1, "text": "a", "difficulty": "easy"}, {"id": 2, "text": "b", "difficulty": "easy"}], attempts)
        self.assertEqual(items[0]["percent_correct"], 50.0)
        self.assertGreater(items[0]["discrimination"], 0.5)      # good question: strong students get it
        self.assertLess(items[1]["discrimination"], 0)           # inverted: strong students miss it
        self.assertTrue(items[1]["weak"])
        self.assertFalse(items[0]["weak"])
        self.assertEqual(items[0]["avg_time_sec"], 10)


if __name__ == "__main__":
    unittest.main()
