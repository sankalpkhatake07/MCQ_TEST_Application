# ExamHub — MCQ Evaluator (v2)

Your original app (FastAPI + SQLModel backend, OTP login, exam timer, proctoring snapshots) extended with all 40 features from
`Features_mcq.docx`. The UI is a zero-build single-page app (plain ES modules), so there is nothing to compile.

## Run it

**Quickest (one process, no Docker)**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload                                # open http://localhost:8000
```
The first start creates `backend/data/mcq.db`, an admin, two demo users and a demo exam ("Python Basics (demo)").

| Sign in as | How |
|---|---|
| Student `student@example.com` | "Email code" tab. With `DEV_SHOW_OTP=true` (default in `.env`) the code is shown on the page and printed in the server console |
| Teacher `teacher@example.com` | same |
| Admin `admin@example.com` | "Password" tab, password from `ADMIN_PASSWORD` in `.env` (default `Admin@12345`) |

**Docker (PostgreSQL + Redis + 2 backend replicas behind nginx)**
```bash
echo "SECRET_KEY=$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" > .env
docker compose up --build            # http://localhost:8080
```
In this stack demo users are off and `DEV_SHOW_OTP` is off: set `ALLOW_SEND_EMAIL=true` + SMTP settings in `backend/.env`
(or sign in as the admin with the password and create users). **Camera/microphone need HTTPS** (or `localhost`): put a TLS
terminator in front for real use. Everything is configured by environment variables, documented in `backend/.env.example`.

## Where each feature lives

| # | Feature | Implementation |
|---|---|---|
| 1 | Shuffle questions + options per student | `core/shuffle.py` (seeded per attempt, stored so reloads keep the same order) |
| 2 | Easy / Medium / Hard, auto-balanced exams | `Question.difficulty`; "Auto-balance" in the exam editor → `POST /api/exams/{id}/auto-generate` |
| 3 | Question bank, tags, subject filters | `routers/bank.py`, `/bank` page |
| 4 | Sections (MCQ / True-False / Fill) with per-section timers | `ExamSection`, `core/timing.py` (sequential, server-enforced) |
| 5 | Negative marking (configurable) | `core/scoring.py` — fraction of the question's marks |
| 6 | "Pick N random from the pool" | section field **Pick N random** |
| 7 | Mark for review + answered/unanswered/marked filter | exam page (`take.js`) |
| 8 | Google / Microsoft login | `security.py` verifies ID tokens (set `GOOGLE_CLIENT_ID` / `MICROSOFT_CLIENT_ID`) |
| 9 | MFA (OTP + password, or OTP + Google/Microsoft) | `routers/auth.py`; users opt in under Account, admins can enable per user |
| 10 | IP restriction | exam setting, CIDR/IP list, checked on start and on every attempt call |
| 11 | Browser lockdown | blocks copy/paste/right-click/devtools shortcuts, **logs** attempts |
| 12 | One device at a time | session id in the JWT; a new sign-in locks the old session |
| 13 | Full-screen / tab / focus enforcement | warns, counts violations, auto-submits at the teacher's limit |
| 14–18 | Face match, multi-person, gaze, voice, phone | `frontend/js/proctor.js` (in-browser; see limitations) |
| 19 | Cheating score /100, event log, snapshot gallery | `core/cheating.py`, attempt detail page |
| 20–22 | Student analytics, item analysis, exam insights | `/me`, results page, `core/analytics.py` |
| 23–24 | Report card, combined PDF, Excel export | `core/reports.py` (reportlab, openpyxl) |
| 25 | Import from PDF / Word (+ CSV / JSON) | `core/importers.py` |
| 26 | Rich-text editor (bold/italic, images, code) | `js/editor.js` + server-side HTML sanitiser |
| 27–28 | Admin panel, multiple teachers, bulk student CSV | `/admin`, `/students` |
| 29 | Scheduling: visible-from, open, close | auto open/close is computed from timestamps, no cron needed |
| 30 | Cloud storage | `storage.py`: local / S3 / Azure Blob / GCS (snapshots, images, generated PDFs/Excel) |
| 31 | PostgreSQL / MySQL / MongoDB | `DATABASE_URL`; MongoDB receives a mirror of proctoring events (`MONGO_URL`) |
| 32 | Load balancing | `deploy/nginx.conf`, compose replicas, Redis pub/sub in `events.py` |
| 33–36 | Dark mode, accessibility, Saved/Pending/Offline, live progress | header controls, exam bar and answer sheet |
| 37 | Practice mode | opens after the exam closes or after the student submits; answers revealed |
| 38 | Live ranking | leaderboard page, updates over Server-Sent Events |
| 39 | Certificate PDF + public verification | `GET /api/certificates/verify/{code}` |
| 40 | English / हिन्दी / मराठी, teacher picks allowed languages | `frontend/i18n/*.json` — add a language by adding a JSON file and one entry in `LANGS` (`js/i18n.js`, `app/config.py`) |

## Design decisions worth knowing

* **Server-authoritative clock.** All times are UTC with a trailing `Z` (the old code sent naive times, which browsers read as *local* time: a 5.5 h error in India). The client syncs to server time.
* **Offline handling changed.** Calling `/pause` once the network is already gone can never reach the server, and a student could fake "offline" to freeze the clock. Instead the client buffers answers/events/snapshots, and on reconnect `POST /attempts/{id}/sync` credits the outage — capped by what the server itself observed (gap since last contact) and by `OFFLINE_CREDIT_CAP_SECONDS` (default 10 min). `/pause` and `/resume` still exist, with the same cap.
* **Students never get answers or the question list up front.** Questions come through the attempt (`/attempts/{id}/state`) in the student's own shuffled order, only the open section's questions when sections are timed, and correct answers only after submission if the teacher allows it. `GET /exams/{id}/questions` is therefore teacher-only.
* **Imports never guess.** A question without a valid answer is skipped and reported (the old CSV importer silently made option A correct).
* **Locked once started.** After the first student starts, questions, sections, negative marking and shuffle rules are locked, and bank questions used by a started exam can't be edited. Use "Reset attempt" for a student who must retake.
* **API prefix** is `/api/...`. Legacy `/combined-login.html` etc. redirect to the new app. Old `dev.db` data is not migrated (the schema changed substantially); the new default database is `data/mcq.db`.
* **PDFs use reportlab**, not WeasyPrint (no system libraries needed). Complex scripts such as Devanagari conjuncts can't be shaped by reportlab, so names in Hindi/Marathi may render imperfectly in PDFs; on-screen views and Excel are fine.

## Honest limitations

* **Browsers cannot truly lock a computer.** Lockdown and "prevent tab switching" detect, log and (optionally) auto-submit — they can't stop someone using a second device. Treat the cheating score as a prompt for human review, not proof.
* **AI proctoring runs in the student's browser** and loads face-api.js / TensorFlow.js models from a CDN (jsDelivr). Offline college networks need those files self-hosted (change the URLs at the top of `js/proctor.js`). If the models can't load, proctoring continues with snapshots only and an `ai_unavailable` note is logged. Head-turn "gaze" is estimated from head pose, not true eye tracking. Phone detection is best-effort.
* The JWT is kept in `localStorage` (sent as a Bearer header); an HttpOnly-cookie mode is not implemented.
* Scale-out: use PostgreSQL + Redis (+ shared object storage) with several replicas. SQLite is for development only.

## Tests

```bash
cd backend && python -m unittest discover -s tests -v       # 31 tests of the core logic (scoring, shuffle, timing, importers, sanitiser…)
python tests/ui/test_ui.py                                  # 63 browser checks (needs: pip install playwright && playwright install chromium)
```
