# Browser smoke test: drives the real UI in headless Chromium against a mocked API.
# pip install playwright && playwright install chromium && python tests/ui/test_ui.py
import json, os, re, sys, threading, time, http.server, socketserver, functools
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
FRONT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
PORT = 8099

# ---------------------------------------------------------------- static server with SPA fallback
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=FRONT, **k)
    def do_GET(self):
        p = self.path.split("?")[0]
        if not os.path.isfile(os.path.join(FRONT, p.lstrip("/"))) and not p.startswith("/api"):
            self.path = "/index.html"
        return super().do_GET()
    def log_message(self, *a): pass
socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

def iso(dt): return dt.replace(microsecond=0, tzinfo=None).isoformat() + "Z"
NOW = lambda: datetime.now(timezone.utc)
XSS_TITLE = "Python <img src=x onerror=window.__xss=1> Basics"

# ---------------------------------------------------------------- mock API
class Mock:
    def __init__(self):
        self.expires = NOW() + timedelta(minutes=15)
        self.log = []          # (method, path, body)
        self.submitted = False
        self.answers = {}
        self.marked = []
        self.events = []
    def exam(self, full=False):
        e = dict(id=1, title=XSS_TITLE, description="Sample", instructions="Be honest.", duration_min=15, status="open", published=True,
                 start_at=None, end_at=None, visible_from=None, lockdown=True, fullscreen_required=False, camera_required=True, mic_enabled=False,
                 ai_proctoring=False, negative_mark=0.25, pass_percent=40, practice_enabled=True, live_ranking=True, certificate_enabled=True,
                 shuffle_questions=True, shuffle_options=True, languages=["en", "hi", "mr"], show_result=True, show_answers=True,
                 snapshot_interval=10, max_violations=3, question_count=3)
        if full:
            e.update(closed_manual=False, strict_end=True, allowed_ips=[], owner_id=2, locked=False, attempt_count=1, submitted_count=0,
                     sections=[dict(id=10, name="Section A", qtype="mixed", duration_min=None, pick_count=None, position=0, question_ids=[1, 2, 3])],
                     questions=[dict(id=1, section_id=10, qtype="mcq", text="<p>What is <b>1+1</b>?</p>", choices=["1", "2"], correct=1, marks=1, difficulty="easy", tags=["Basics"], subject="Py", explanation=None),
                                dict(id=2, section_id=10, qtype="tf", text="<p>Sky is blue</p>", choices=["True", "False"], correct=0, marks=1, difficulty="medium", tags=[], subject="Py", explanation=None),
                                dict(id=3, section_id=10, qtype="fill", text="<p>Capital of India is ____</p>", choices=[], correct=["Delhi"], marks=1, difficulty="hard", tags=[], subject="Py", explanation=None)])
        else:
            e["my_attempt"] = None; e["can_practice"] = False
        return e
    def state(self):
        return dict(attempt=dict(id=7, status="in_progress", is_practice=False, expires_at=iso(self.expires), started_at=iso(NOW()), server_time=iso(NOW()),
                                 timed_sections=False, offline_credit_seconds=0, offline_credit_cap=600),
                    exam={**self.exam(), "total_questions": 3}, sections=[dict(id=10, name="Section A", qtype="mixed", duration_min=None, count=3, status="active", deadline=None)],
                    questions=[dict(id=1, section_id=10, type="mcq", text="<p>What is <b>1+1</b>?<script>window.__xss2=1</script><img src=x onerror=window.__xss3=1></p>", choices=[dict(i=1, t="2"), dict(i=0, t="1")], marks=1),
                               dict(id=2, section_id=10, type="tf", text="<p>Sky is blue</p>", choices=[dict(i=0, t="True"), dict(i=1, t="False")], marks=1),
                               dict(id=3, section_id=10, type="fill", text="<p>Capital of India is ____</p>", choices=[], marks=1)],
                    answers=dict(self.answers), marked=list(self.marked), times={}, violations=len(self.events))
    def live(self): return dict(status="submitted" if self.submitted else "in_progress", server_time=iso(NOW()), expires_at=iso(self.expires), violations=len(self.events), sections={})

    def handle(self, method, path, body, auth):
        self.log.append((method, path, body))
        teacher = auth == "Bearer ttok"
        J = lambda d, s=200: (s, d)
        if path == "/api/auth/config": return J(dict(google_client_id=None, microsoft_client_id=None, allow_otp_only=True, languages={"en": "English"}, dev_otp=True))
        if path == "/api/auth/request-otp": return J(dict(detail="otp_sent", dev_otp="123456"))
        if path == "/api/auth/verify-otp":
            em = body["email"]
            role = "teacher" if em.startswith("teacher") else "student"
            return J(dict(access="ttok" if teacher or role == "teacher" else "stok", user=dict(id=2 if role == "teacher" else 1, email=em, name="Asha", role=role, has_password=False, mfa_enabled=False)))
        if path == "/api/auth/me": return J(dict(id=2 if teacher else 1, email="x@y.z", name="Asha", role="teacher" if teacher else "student", has_password=False, mfa_enabled=False))
        if path == "/api/exams" and method == "GET":
            if teacher: return J([{**self.exam(True), "question_count": 3, "attempt_count": 1, "submitted_count": 1}])
            return J([self.exam()])
        if path == "/api/exams/1" and method == "GET": return J(self.exam(True) if teacher else self.exam())
        if path.startswith("/api/exams/1/start"): return J(dict(attempt_id=7, status="in_progress", is_practice=False, expires_at=iso(self.expires), server_time=iso(NOW())))
        if path == "/api/attempts/7/state": return J(dict(submitted=True, attempt_id=7) if self.submitted else self.state())
        if path == "/api/attempts/7/answer":
            if body.get("value") is None: self.answers.pop(str(body["question_id"]), None)
            else: self.answers[str(body["question_id"])] = body["value"]
            if body.get("marked") is True: self.marked.append(body["question_id"])
            return J(dict(saved=True, **self.live()))
        if path == "/api/attempts/7/heartbeat": return J(self.live())
        if path == "/api/attempts/7/events":
            self.events.append(body); return J(dict(auto_submitted=len(self.events) >= 10, violations=len(self.events), max_violations=3))
        if path == "/api/attempts/7/snapshot": return J(dict(saved=True))
        if path == "/api/attempts/7/sync":
            for a in body.get("answers", []): self.answers[str(a["question_id"])] = a["value"]
            self.expires += timedelta(seconds=min(30, body.get("offline_seconds", 0)))
            return J(dict(**self.live(), credit_seconds=min(30, int(body.get("offline_seconds", 0))), rejected=[], auto_submitted=False))
        if path == "/api/attempts/7/submit": self.submitted = True; return J(dict(ok=True))
        if path == "/api/attempts/7/result":
            return J(dict(attempt_id=7, exam_id=1, exam_title=XSS_TITLE, status="submitted", is_practice=False, score=2.75, max_score=3, percent=91.7, correct=3, wrong=0, unanswered=0,
                          passed=True, pass_percent=40, seconds=125, submit_reason="manual", cheating_score=0, by_topic={"Basics": dict(total=2, correct=2, percent=100, score=2, max=2)},
                          by_section=[dict(id="10", name="Section A", total=3, correct=3, score=3, max=3, percent=100)], answers_revealed=True, certificate_available=True, rank=dict(position=1, of=4),
                          review=[dict(id=1, text="<p>What is 1+1?</p>", type="mcq", status="correct", awarded=1, given_text="2", correct_text="2", explanation="<p>Math.</p>", time=12, choices=[])]))
        if path == "/api/me/analytics": return J(dict(attempts=2, trend=[dict(attempt_id=7, exam="E1", percent=60, practice=False, date=iso(NOW())), dict(attempt_id=8, exam="E1", percent=90, practice=True, date=iso(NOW()))], topics={"Loops": dict(total=4, correct=1, percent=25)}, avg_time_per_question=14, average_percent=75))
        if path == "/api/bank/meta": return J(dict(subjects=["Py"], tags=["Basics"], total=3, by_difficulty=dict(easy=1, medium=1, hard=1)))
        if path.startswith("/api/bank") and method == "GET": return J(dict(total=1, page=1, size=20, items=self.exam(True)["questions"][:1]))
        if path == "/api/exams/1/analytics":
            dist = [dict(label=f"{i*10}-{i*10+10}", count=c) for i, c in enumerate([0, 0, 1, 0, 2, 3, 4, 2, 1, 1])]
            return J(dict(exam=self.exam(), insights=dict(count=14, highest=9, lowest=2, average=6.2, median=6, pass_rate=71.4, avg_time_min=11.5, distribution=dist),
                          items=[dict(question_id=1, text="<p>Q</p>", labelled="easy", attempts=14, correct=10, wrong=3, skipped=1, percent_correct=71.4, observed_difficulty="medium", discrimination=0.4, avg_time_sec=12, weak=False)],
                          topics={"Basics": dict(total=10, correct=7, percent=70)}, risk=dict(low=10, medium=3, high=1), in_progress=2))
        if path == "/api/exams/1/attempts": return J([dict(attempt_id=7, user_id=1, name="Asha", email="a@x", roll_no="1", status="submitted", score=2.75, max_score=3, percent=91.7, correct=3, wrong=0, unanswered=0, seconds=125, cheating_score=35, cheating_level="medium", violations=1, submit_reason="manual")])
        if path.startswith("/api/live/ticket"): return J(dict(ticket="t"))
        return J(dict(detail=f"mock: unhandled {method} {path}"), 404)

# ---------------------------------------------------------------- test run
fails, results = [], []
def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

def run():
    m = Mock()
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True, args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
        ctx = br.new_context(permissions=["camera", "microphone"], viewport={"width": 1280, "height": 900}, color_scheme="light")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        page.on("console", lambda msg: errors.append("console.error: " + msg.text) if msg.type == "error" and "Failed to load resource" not in msg.text and "mock: unhandled" not in msg.text else None)
        def route(r):
            req = r.request
            path = re.sub(r"^https?://[^/]+", "", req.url).split("?")[0] if "?" not in req.url else re.sub(r"^https?://[^/]+", "", req.url).split("?")[0]
            full = re.sub(r"^https?://[^/]+", "", req.url)
            if path == "/api/live/stream": return r.fulfill(status=200, headers={"content-type": "text/event-stream"}, body=": hi\n\n")
            try: body = json.loads(req.post_data) if req.post_data and "json" in (req.headers.get("content-type") or "") else {}
            except Exception: body = {}
            status, data = m.handle(req.method, full if full.startswith("/api/exams/1/start") or full.startswith("/api/bank") or full.startswith("/api/live/ticket") else path, body, req.headers.get("authorization"))
            r.fulfill(status=status, content_type="application/json", body=json.dumps(data))
        page.route("**/api/**", route)

        base = f"http://127.0.0.1:{PORT}"
        # ---------------- login
        page.goto(base + "/")
        page.wait_for_selector("#em")
        check("unauthenticated user lands on login", "#/login" in page.url)
        page.fill("#em", "asha@example.com"); page.click("#f-email button")
        page.wait_for_selector("#cd")
        check("dev OTP hint shown", "123456" in page.inner_text(".auth-form"))
        page.fill("#cd", "123456"); page.click("#f-code button")
        page.wait_for_selector(".exam-card")
        check("student lands on exam list", "#/exams" in page.url)
        check("XSS in exam title is shown as text, not executed", page.evaluate("window.__xss") is None and "<img" in page.inner_text(".exam-card h3"))

        # ---------------- i18n + theme + font
        page.select_option("#lang-sel", "hi"); page.wait_for_timeout(300)
        check("Hindi UI applied", "मेरी परीक्षाएँ" in page.inner_text("h1"), page.inner_text("h1"))
        check("html lang attribute follows language", page.evaluate("document.documentElement.lang") == "hi")
        page.select_option("#lang-sel", "mr"); page.wait_for_timeout(300)
        check("Marathi UI applied", "माझ्या परीक्षा" in page.inner_text("h1"))
        page.select_option("#lang-sel", "en"); page.wait_for_timeout(300)
        page.click("[data-a=theme]"); page.click("[data-a=theme]")
        check("dark theme toggle works", page.evaluate("document.documentElement.dataset.theme") == "dark")
        fs0 = page.evaluate("getComputedStyle(document.documentElement).fontSize")
        page.click("[data-a='font+']")
        check("A+ enlarges text", page.evaluate("getComputedStyle(document.documentElement).fontSize") != fs0)
        page.click("[data-a=contrast]")
        check("high contrast toggle", page.evaluate("document.documentElement.dataset.contrast") == "high")
        page.click("[data-a=contrast]"); page.click("[data-a=theme]")   # back to light/auto

        # ---------------- instructions -> camera check -> start
        page.click(".exam-card .btn.primary"); page.wait_for_selector("#agree")
        check("rules list shows lockdown + camera", "right-click" in page.inner_text("main") and "camera" in page.inner_text("main").lower())
        check("begin disabled until camera ok and agreed", page.is_disabled("#go"))
        page.click("#cam"); page.wait_for_timeout(600)
        page.check("#agree")
        check("begin enabled after camera check + agree", not page.is_disabled("#go"))
        page.click("#go"); page.wait_for_selector(".exam-bar")
        check("exam screen opens", "#/take/7" in page.url)
        check("body is in exam mode (nav hidden)", page.evaluate("document.body.dataset.mode") == "exam")
        check("lockdown class applied", page.evaluate("document.body.classList.contains('lockdown')"))
        check("XSS payloads in question HTML neutralised", page.evaluate("window.__xss2 === undefined && window.__xss3 === undefined") and page.locator(".qtext b").count() == 1)

        # ---------------- timer
        t1 = page.inner_text("#timer")
        check("timer shows ~15:00", re.match(r"^1[45]:\d\d$", t1) is not None, t1)
        page.wait_for_timeout(2300)
        check("timer counts down", page.inner_text("#timer") != t1)

        # ---------------- answering, autosave, mark, palette
        page.locator(".opt").first.click(); page.wait_for_timeout(400)
        check("answer POSTed to server", any(p_ == "/api/attempts/7/answer" and b.get("question_id") == 1 and b.get("value") == 1 for _, p_, b in m.log))
        check("palette bubble shows answered", "ans" in page.get_attribute("[data-goto='0']", "class"))
        check("save indicator says Saved", "Saved" in page.inner_text("#save"))
        page.click("[data-act=mark]"); page.wait_for_timeout(300)
        check("mark-for-review recorded", 1 in m.marked and "mk" in page.get_attribute("[data-goto='0']", "class"))
        page.click("[data-filter=marked]")
        check("filter 'marked' hides unmarked bubbles", page.locator(".bub").count() == 1)
        page.click("[data-filter=all]")
        page.keyboard.press("ArrowRight"); page.wait_for_timeout(200)
        check("ArrowRight goes to Q2", "2" in page.inner_text(".qno"))
        page.keyboard.press("2"); page.wait_for_timeout(400)   # 2nd option of TF = False (value 1)
        check("number key selects option", m.answers.get("2") == 1, str(m.answers))
        page.click("[data-act=next]"); page.fill("#fillin", "Delhi"); page.wait_for_timeout(1100)
        check("fill-in answer autosaved (debounced)", m.answers.get("3") == "Delhi", str(m.answers))
        page.click("[data-act=clear]"); page.wait_for_timeout(300)
        check("clear answer sends null", "3" not in m.answers)
        page.fill("#fillin", "Delhi"); page.wait_for_timeout(1000)

        # ---------------- proctoring: camera snapshots
        page.wait_for_timeout(7500)
        snaps = [b for _, p_, b in m.log if p_ == "/api/attempts/7/snapshot"]
        check("webcam snapshots uploaded (JPEG)", snaps and snaps[0]["image"].startswith("data:image/jpeg;base64,"), str(len(snaps)))
        check("camera preview visible", page.is_visible("#pcam video"))

        # ---------------- offline -> queue -> sync with credit
        ctx.set_offline(True)
        page.locator("[data-goto='0']").click(); page.locator(".opt").nth(1).click(); page.wait_for_timeout(600)
        check("offline: indicator turns to offline", "Offline" in page.inner_text("#save"), page.inner_text("#save"))
        q = json.loads(page.evaluate("localStorage.getItem('examhub.q.7')"))
        check("offline: answer persisted locally", q["answers"].get("1", {}).get("value") == 0 and q["offlineSince"], str(q))
        page.wait_for_timeout(2500)
        ctx.set_offline(False)
        page.evaluate("window.dispatchEvent(new Event('online'))"); page.wait_for_timeout(1500)
        syncs = [b for _, p_, b in m.log if p_ == "/api/attempts/7/sync"]
        carry = [b for b in syncs if any(a["question_id"] == 1 and a["value"] == 0 for a in b["answers"])]
        check("back online: buffered answers synced", len(carry) == 1)
        check("sync reports offline seconds for credit", carry and carry[0]["offline_seconds"] > 0.5, str(carry and carry[0]["offline_seconds"]))
        check("answers are not re-sent once acknowledged", sum(len(b["answers"]) for b in syncs) == 1)
        check("indicator back to Saved", "Saved" in page.inner_text("#save"))
        check("local queue cleared after sync", json.loads(page.evaluate("localStorage.getItem('examhub.q.7')"))["offlineSince"] is None)

        # ---------------- integrity guards
        ev0 = len(m.events)
        prevented = page.evaluate("(() => { const e = new Event('contextmenu', {cancelable:true}); document.dispatchEvent(e); return e.defaultPrevented; })()")
        check("lockdown blocks right-click", prevented)
        page.evaluate("document.dispatchEvent(new Event('copy', {cancelable:true}))"); page.wait_for_timeout(400)
        check("copy attempt reported", any(e["type"] == "copy_paste" for e in m.events[ev0:]))
        page.keyboard.press("F12"); page.wait_for_timeout(300)
        check("F12 blocked + reported", any(e["type"] == "blocked_shortcut" for e in m.events))
        page.evaluate("Object.defineProperty(document,'hidden',{value:true,configurable:true}); document.dispatchEvent(new Event('visibilitychange'))"); page.wait_for_timeout(400)
        check("tab switch reported", any(e["type"] == "tab_switch" for e in m.events))
        page.evaluate("Object.defineProperty(document,'hidden',{value:false,configurable:true}); document.dispatchEvent(new Event('visibilitychange'))")
        check("violation warning banner shown", page.is_visible(".banner.warn"), page.inner_text("#body")[:200])

        # ---------------- language change inside exam keeps the attempt
        page.select_option("#lang-sel", "hi"); page.wait_for_timeout(400)
        check("exam UI switches language in place", "प्रश्न" in page.inner_text(".qno") and "#/take/7" in page.url)
        page.select_option("#lang-sel", "en"); page.wait_for_timeout(300)

        # ---------------- submit
        page.click("[data-act=submit] >> nth=0"); page.wait_for_selector(".modal")
        check("submit confirmation lists counts", "3" in page.inner_text(".modal"))
        page.click(".modal [data-yes]"); page.wait_for_selector(".score-ring", timeout=8000)
        check("redirected to result page", "#/result/7" in page.url)
        txt = page.inner_text("main")
        check("result shows percent, pass state, rank, correct answer", "91.7" in txt and "Passed" in txt and "#1" in txt and "Correct answer" in txt, txt[:300])
        check("report + certificate buttons present", page.locator("[data-dl=report]").count() == 1 and page.locator("[data-dl=cert]").count() == 1)
        check("beforeunload guard released after submit", page.evaluate("window.onbeforeunload") is None)

        page.goto(base + "/#/me"); page.wait_for_selector(".charts svg")
        check("student progress page: trend chart + weak topic warning", page.locator("svg circle").count() >= 2 and "Loops" in page.inner_text("main"))

        # ---------------- teacher
        page.evaluate("localStorage.clear()")
        page.goto(base + "/#/login"); page.reload(); page.wait_for_selector("#em")
        page.fill("#em", "teacher@example.com"); page.click("#f-email button"); page.wait_for_selector("#cd")
        page.fill("#cd", "123456"); page.click("#f-code button")
        page.wait_for_selector("table")
        check("teacher lands on exam dashboard", "#/teacher" in page.url and "Question bank" in page.inner_text(".nav"))
        check("teacher XSS title escaped", page.evaluate("window.__xss") is None)
        page.goto(base + "/#/teacher/exam/1"); page.wait_for_selector("#setup")
        check("exam editor settings render (negative marking, lockdown, IP rules)", all(s in page.inner_text("main") for s in ["Negative marking", "Browser lockdown", "Allowed IP", "Practice mode", "Live ranking", "Certificate"]))
        page.click("[data-tab=questions]"); page.wait_for_selector("#sections")
        check("question tab: sections, import, bank, auto-balance", all(s in page.inner_text("main") for s in ["Import PDF", "From bank", "Auto-balance", "Pick N random"]))
        page.click("[data-a=new-q]"); page.wait_for_selector(".rte-body")
        check("question editor modal with rich-text toolbar", page.locator(".rte-bar button").count() >= 8)
        page.click(".rte-body"); page.keyboard.type("Hello"); page.click("[data-cmd=bold]")
        page.click("[data-cancel]")
        page.click("[data-tab=share]"); check("share tab shows exam id + link", "Exam ID" in page.inner_text("main"))
        page.goto(base + "/#/bank"); page.wait_for_selector(".q-list-item")
        check("bank page lists questions with filters", page.locator("#fs").count() == 1 and page.locator(".q-list-item").count() == 1)
        page.goto(base + "/#/teacher/exam/1/results"); page.wait_for_selector(".stat")
        check("results overview: stats + distribution + risk donut", page.locator(".charts svg rect").count() >= 10 and page.locator("svg circle").count() >= 3)
        page.click("[data-tab=students]"); page.wait_for_selector("table")
        check("students tab: risk badge + export buttons", "35 · medium" in page.inner_text("main") and page.locator("[data-dl]").count() == 2)
        page.click("[data-tab=items]"); check("item analysis tab", "Discrim" in page.inner_text("main"))
        page.click("[data-tab=live]"); check("live monitor tab", "Live proctoring feed" in page.inner_text("main"))
        page.goto(base + "/#/admin"); page.wait_for_timeout(500)
        check("teacher blocked from admin page", "#/admin" not in page.url)
        page.goto(base + "/#/nonexistent"); page.wait_for_selector(".empty")
        check("unknown route shows not-found", "Page not found" in page.inner_text("main"))

        check("no JavaScript errors in the console", not errors, "\n".join(errors[:8]))
        br.close()
    print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} UI checks passed")
    srv.shutdown()
    sys.exit(1 if fails else 0)
run()
