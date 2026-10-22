import { api, download } from '../api.js';
import { barChart, confirmDialog, donut, fmtDate, fmtDur, fmtNum, hBars, html, mount, on, rich, stripTags, toast } from '../ui.js';

export const EVENT_LABELS = { tab_switch: 'Switched tab', window_blur: 'Window lost focus', fullscreen_exit: 'Left full screen', face_lost: 'Face not visible', multi_face: 'Several faces', gaze_away: 'Looking away',
  voice: 'Voice / noise', phone: 'Phone detected', identity_mismatch: 'Different person', camera_blocked: 'Camera blocked', copy_paste: 'Copy/paste attempt', blocked_shortcut: 'Blocked shortcut',
  session_replaced: 'Signed in elsewhere', ip_change: 'IP changed', offline: 'Went offline', online: 'Back online', camera_ready: 'Camera started', ai_unavailable: 'AI models unavailable' };
export const riskChip = (lvl, score) => html`<span class="chip ${{ low: 'ok', medium: 'warn', high: 'bad' }[lvl]}">${score} · ${lvl}</span>`;

export default async function examResults({ root, params }) {
  const id = params[0];
  let tab = 'overview', A, rows, sortBy = 'rank', feed = [], es = null, closed = false, poll = null, retry = null;
  const load = async () => { [A, rows] = await Promise.all([api(`/api/exams/${id}/analytics`), api(`/api/exams/${id}/attempts`)]); };
  await load();
  const ins = () => A.insights;

  const overview = () => html`
    <div class="grid g4 mb"><div class="stat"><b>${ins().count}</b><span>Submitted</span></div><div class="stat"><b>${A.in_progress}</b><span>In progress</span></div><div class="stat"><b>${fmtNum(ins().average)}</b><span>Average score</span></div>
      <div class="stat"><b>${fmtNum(ins().median)}</b><span>Median</span></div><div class="stat"><b>${fmtNum(ins().highest)}</b><span>Highest</span></div><div class="stat"><b>${fmtNum(ins().lowest)}</b><span>Lowest</span></div>
      <div class="stat"><b>${ins().pass_rate}%</b><span>Pass rate (≥${A.exam.pass_percent}%)</span></div><div class="stat"><b>${ins().avg_time_min}m</b><span>Average time</span></div></div>
    <div class="grid g2"><div class="card charts"><div class="chart-title">Score distribution (% of marks) — number of students</div>${barChart(ins().distribution.map((d) => ({ label: d.label, value: d.count })))}</div>
      <div class="card"><div class="chart-title">Integrity risk</div><div class="row">${donut([{ label: 'Low', value: A.risk.low, color: 'var(--ok)' }, { label: 'Medium', value: A.risk.medium, color: 'var(--warn)' }, { label: 'High', value: A.risk.high, color: 'var(--bad)' }])}
        <div class="small"><div><span class="chip ok">low</span> ${A.risk.low}</div><div class="mt"><span class="chip warn">medium</span> ${A.risk.medium}</div><div class="mt"><span class="chip bad">high</span> ${A.risk.high}</div></div></div></div></div>
    <div class="card mt"><div class="chart-title">Topic performance across all students</div>${Object.keys(A.topics).length ? hBars(Object.entries(A.topics).map(([k, v]) => ({ label: k, value: Math.round(v.percent), sub: `${v.correct}/${v.total} correct` })).sort((a, b) => a.value - b.value)) : html`<p class="muted">No submitted attempts yet.</p>`}</div>`;

  const sorted = () => { const r = [...rows]; const f = { rank: null, name: (a, b) => a.name.localeCompare(b.name), score: (a, b) => b.score - a.score, risk: (a, b) => b.cheating_score - a.cheating_score, time: (a, b) => a.seconds - b.seconds }[sortBy]; return f ? r.sort(f) : r; };
  const students = () => html`
    <div class="row between mb"><div class="row"><label for="sb" class="small" style="margin:0">Sort by</label><select id="sb" style="width:auto">${[['rank', 'Rank'], ['name', 'Name'], ['score', 'Score'], ['risk', 'Integrity risk'], ['time', 'Time']].map(([k, l]) => html`<option value="${k}" ${sortBy === k ? 'selected' : ''}>${l}</option>`)}</select></div>
      <div class="row"><button class="btn sm" data-dl="report.pdf">⬇ Combined PDF</button><button class="btn sm" data-dl="export.xlsx">⬇ Excel</button></div></div>
    <div class="table-wrap"><table><thead><tr><th>#</th><th>Student</th><th>Status</th><th>Score</th><th>%</th><th>Time</th><th>Integrity</th><th></th></tr></thead><tbody>
    ${sorted().length ? sorted().map((r, i) => html`<tr><td>${r.status === 'submitted' ? i + 1 : '—'}</td><td><b>${r.name}</b><div class="tiny muted">${r.roll_no ? r.roll_no + ' · ' : ''}${r.email}</div></td><td><span class="chip ${r.status === 'submitted' ? 'ok' : 'info'}">${r.status.replace('_', ' ')}</span>${r.submit_reason && r.submit_reason !== 'manual' ? html`<div class="tiny muted">${r.submit_reason}</div>` : ''}</td>
      <td>${r.status === 'submitted' ? `${fmtNum(r.score)} / ${fmtNum(r.max_score)}` : '—'}</td><td>${r.status === 'submitted' ? fmtNum(r.percent, 1) : '—'}</td><td>${fmtDur(r.seconds)}</td><td>${riskChip(r.cheating_level, r.cheating_score)}</td>
      <td class="nowrap"><a class="btn sm" href="#/teacher/attempt/${r.attempt_id}">Details</a> <button class="btn sm danger" data-reset="${r.attempt_id}" data-name="${r.name}">Reset</button></td></tr>`) : html`<tr><td colspan="8" class="empty">No attempts yet.</td></tr>`}</tbody></table></div>`;

  const items = () => html`<p class="muted small">“Discrimination” compares how well top and bottom scorers did on the question: near zero or negative suggests the question or its key may be flawed. Needs at least 4 submissions.</p>
    <div class="table-wrap"><table><thead><tr><th>#</th><th>Question</th><th>% correct</th><th>Difficulty (observed / labelled)</th><th>Discrim.</th><th>Right / Wrong / Skipped</th><th>Avg time</th><th></th></tr></thead><tbody>
    ${A.items.map((q, i) => html`<tr><td>${i + 1}</td><td style="max-width:340px">${stripTags(q.text).slice(0, 110)}</td><td><div class="bar ${q.percent_correct >= 70 ? 'ok' : q.percent_correct >= 35 ? '' : 'bad'}" style="width:90px"><i style="width:${q.percent_correct}%"></i></div>${q.percent_correct}%</td>
      <td>${q.observed_difficulty || '—'} / ${q.labelled || '—'}</td><td>${q.discrimination ?? '—'}</td><td>${q.correct} / ${q.wrong} / ${q.skipped}</td><td>${q.avg_time_sec}s</td><td>${q.weak ? html`<span class="chip bad">review</span>` : ''}</td></tr>`)}</tbody></table></div>`;

  const live = () => html`<div class="grid g2"><section class="card"><h3><span class="live-dot"></span>Live proctoring feed</h3>
      <div class="timeline" id="feed">${feed.length ? feed.map(feedRow) : html`<div class="muted">Waiting for activity… events appear here as students take the exam.</div>`}</div></section>
    <section class="card"><h3>In progress (${rows.filter((r) => r.status !== 'submitted').length})</h3>
      ${rows.filter((r) => r.status !== 'submitted').map((r) => html`<div class="row between" style="padding:.4rem 0;border-bottom:1px solid var(--line)"><span>${r.name}</span><span>${riskChip(r.cheating_level, r.cheating_score)} <a class="btn sm" href="#/teacher/attempt/${r.attempt_id}">Open</a></span></div>`)}
      ${rows.some((r) => r.status !== 'submitted') ? '' : html`<p class="muted">Nobody is taking this exam right now.</p>`}</section></div>`;
  const nameOf = (aid) => rows.find((r) => r.attempt_id === aid)?.name || `Attempt ${aid}`;
  const feedRow = (f) => html`<div><time>${new Date(f.ts).toLocaleTimeString()}</time><span><b>${nameOf(f.attempt_id)}</b> — ${f.label}${f.detail ? html` <span class="muted">(${f.detail})</span>` : ''}</span></div>`;

  const draw = () => mount(root, html`
    <div class="row between"><div><a href="#/teacher" class="small">← All exams</a><h1>${A.exam.title}: results</h1></div><a class="btn" href="#/teacher/exam/${id}">Edit exam</a></div>
    <div class="tabs" role="tablist">${[['overview', 'Overview'], ['students', 'Students'], ['items', 'Question analysis'], ['live', 'Live monitor']].map(([k, l]) => html`<button role="tab" aria-selected="${tab === k}" data-tab="${k}">${l}</button>`)}</div>
    ${tab === 'overview' ? overview() : tab === 'students' ? students() : tab === 'items' ? items() : live()}`);
  draw();

  on(root, 'click', '[data-tab]', (e, el) => { tab = el.dataset.tab; draw(); });
  on(root, 'change', '#sb', (e) => { sortBy = e.target.value; draw(); });
  on(root, 'click', '[data-dl]', async (e, el) => { try { await download(`/api/exams/${id}/${el.dataset.dl}`, el.dataset.dl); } catch (er) { toast(er.message, 'bad'); } });
  on(root, 'click', '[data-reset]', async (e, el) => {
    if (await confirmDialog(`Delete ${el.dataset.name}'s attempt so they can take the exam again? Their answers, score and snapshots are removed.`, { okText: 'Reset attempt', danger: true })) {
      try { await api(`/api/attempts/${el.dataset.reset}`, { method: 'DELETE' }); toast('Attempt reset', 'ok'); await load(); draw(); } catch (er) { toast(er.message, 'bad'); }
    }
  });

  async function connect() {
    if (closed) return;
    try {
      const { ticket } = await api(`/api/live/ticket/${id}?kind=proctor`, { method: 'POST', quiet: true });
      es = new EventSource(`/api/live/stream?t=${encodeURIComponent(ticket)}`);
      es.onmessage = async (m) => {
        const d = JSON.parse(m.data);
        if (d.type === 'event') { feed.unshift({ ...d, label: EVENT_LABELS[d.event] || d.event }); feed = feed.slice(0, 100); if (!rows.some((r) => r.attempt_id === d.attempt_id)) await load(); const r = rows.find((x) => x.attempt_id === d.attempt_id); if (r) r.cheating_score = d.cheating_score; if (tab === 'live') draw(); }
        else if (d.type === 'submitted') { await load(); if (tab !== 'items') draw(); }
      };
      es.onerror = () => { es.close(); retry = setTimeout(connect, 5000); };
    } catch { retry = setTimeout(connect, 8000); }
  }
  connect();
  poll = setInterval(async () => { if (tab === 'students' || tab === 'live') { try { await load(); draw(); } catch { /* ignore */ } } }, 30000);
  return () => { closed = true; es?.close(); clearInterval(poll); clearTimeout(retry); };
}
