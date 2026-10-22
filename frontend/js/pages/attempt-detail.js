import { api, download } from '../api.js';
import { confirmDialog, fmtDate, fmtDur, fmtNum, html, mount, on, openModal, rich, toast } from '../ui.js';
import { EVENT_LABELS, riskChip } from './exam-results.js';

export default async function attemptDetail({ root, params, go }) {
  const id = params[0];
  const [r, p] = await Promise.all([api(`/api/attempts/${id}/result`), api(`/api/attempts/${id}/proctor`)]);
  const counts = {}; p.events.forEach((e) => { counts[e.type] = (counts[e.type] || 0) + 1; });
  mount(root, html`
    <div class="row between"><div><a href="#/teacher/exam/${r.exam_id}/results" class="small">← Results</a><h1>${r.student.name || r.student.email}</h1>
      <p class="muted">${r.student.roll_no ? r.student.roll_no + ' · ' : ''}${r.student.email} · ${r.exam_title}</p></div>
      <div class="row"><button class="btn" data-dl>⬇ Report card (PDF)</button><button class="btn danger" data-reset>Reset attempt</button></div></div>
    <div class="grid g4 mb"><div class="stat"><b>${r.status === 'submitted' ? `${fmtNum(r.score)} / ${fmtNum(r.max_score)}` : '—'}</b><span>Score</span></div><div class="stat"><b>${fmtNum(r.percent, 1)}%</b><span>${r.passed ? 'Passed' : 'Below pass mark'}</span></div>
      <div class="stat"><b>${fmtDur(r.seconds)}</b><span>Time taken</span></div><div class="stat"><b>${r.violations}</b><span>Tab / full-screen violations</span></div></div>
    <div class="grid g2"><section class="card"><h3>Integrity score ${riskChip(p.level, p.cheating_score)}</h3><div class="gauge" role="img" aria-label="${p.cheating_score} out of 100"><i style="left:${p.cheating_score}%"></i></div>
        <p class="hint">A guide for review, not a verdict: each event type adds points up to a cap. Look at the snapshots and timeline before deciding.</p>
        <div class="row">${Object.entries(counts).map(([k, n]) => html`<span class="chip">${EVENT_LABELS[k] || k} × ${n}</span>`)}</div>
        ${r.offline_credit_seconds ? html`<p class="small muted mt">Connection drops: ${r.offline_credit_seconds}s of time was credited back.</p>` : ''}
        ${r.submit_reason && r.submit_reason !== 'manual' ? html`<p class="banner warn small">Auto-submitted: ${r.submit_reason}</p>` : ''}</section>
      <section class="card"><h3>Event timeline</h3><div class="timeline">${p.events.length ? p.events.map((e) => html`<div><time>${new Date(e.ts).toLocaleTimeString()}</time><span>${EVENT_LABELS[e.type] || e.type}${e.detail ? html` <span class="muted">(${e.detail})</span>` : ''}</span></div>`) : html`<div class="muted">No events recorded.</div>`}</div></section></div>
    <section class="card mt"><h3>Snapshots (${p.snapshots.length})</h3>${p.snapshots.length ? html`<div class="gallery">${p.snapshots.map((s) => html`<figure style="margin:0"><img src="${s.url}" alt="Snapshot at ${new Date(s.ts).toLocaleTimeString()}" loading="lazy" data-full="${s.url}"><figcaption class="tiny muted">${new Date(s.ts).toLocaleTimeString()}${s.label ? ' · ' + s.label : ''}</figcaption></figure>`)}</div>` : html`<p class="muted">No snapshots (webcam was not required, or none were uploaded).</p>`}</section>
    <section class="card mt"><h3>Answers</h3>${r.review.map((q, i) => html`<div class="review-q ${q.status}"><div class="row between"><b>Q${i + 1}</b><span class="chip ${q.status === 'correct' ? 'ok' : q.status === 'wrong' ? 'bad' : ''}">${q.status} · ${q.awarded}</span></div>
      <div class="qtext">${rich(q.text)}</div><div class="small"><b>Answer:</b> ${q.given_text || '—'} &nbsp; <b>Correct:</b> <span style="color:var(--ok)">${q.correct_text}</span> &nbsp; <span class="muted">⏱ ${q.time}s</span></div></div>`)}</section>`);
  on(root, 'click', '[data-full]', (e, el) => openModal({ title: 'Snapshot', wide: true, body: html`<img src="${el.dataset.full}" alt="Snapshot" style="width:100%;border-radius:8px">` }));
  on(root, 'click', '[data-dl]', async () => { try { await download(`/api/attempts/${id}/report.pdf`, 'report.pdf'); } catch (e) { toast(e.message, 'bad'); } });
  on(root, 'click', '[data-reset]', async () => { if (await confirmDialog('Delete this attempt so the student can retake the exam?', { okText: 'Reset attempt', danger: true })) { try { await api(`/api/attempts/${id}`, { method: 'DELETE' }); toast('Attempt reset', 'ok'); go(`/teacher/exam/${r.exam_id}/results`); } catch (e) { toast(e.message, 'bad'); } } });
}
