import { api, download } from '../api.js';
import { t } from '../i18n.js';
import { fmtDur, fmtNum, hBars, html, mount, on, rich, toast } from '../ui.js';

export default async function result({ root, params, go }) {
  const id = params[0];
  const r = await api(`/api/attempts/${id}/result`);
  if (r.hidden) {
    mount(root, html`<div class="card center" style="max-width:560px;margin:3rem auto"><h1>✓ ${t('submitted')}</h1><p>${t('results_hidden')}</p><a class="btn primary" href="#/exams">${t('back_to_exams')}</a></div>`);
    return;
  }
  let onlyWrong = false;
  const pass = r.passed, c = pass ? 'var(--ok)' : 'var(--bad)';
  const topics = Object.entries(r.by_topic || {}).map(([k, v]) => ({ label: k, value: Math.round(v.percent), sub: `${v.correct}/${v.total} ${t('correct').toLowerCase()}` })).sort((a, b) => a.value - b.value);
  const secs = (r.by_section || []).length > 1 ? r.by_section.map((s) => ({ label: s.name, value: Math.round(s.percent), sub: `${fmtNum(s.score)} / ${fmtNum(s.max)}` })) : [];
  const note = { timeout: t('ended_timeout'), violations: t('ended_violations') }[r.submit_reason];

  const reviewItem = (q, n) => html`<div class="review-q ${q.status}">
    <div class="row between"><b>${t('question_n', { n, total: r.review.length })}</b><span class="chip ${q.status === 'correct' ? 'ok' : q.status === 'wrong' ? 'bad' : ''}">${t('st_' + q.status)} · ${q.awarded > 0 ? '+' : ''}${q.awarded}</span></div>
    <div class="qtext">${rich(q.text)}</div>
    <div class="small"><b>${t('your_answer')}:</b> ${q.given_text || '—'}</div>
    ${r.answers_revealed ? html`<div class="small"><b>${t('correct_answer')}:</b> <span style="color:var(--ok)">${q.correct_text}</span></div>${q.explanation ? html`<div class="banner small"><b>${t('explanation')}:</b> ${rich(q.explanation)}</div>` : ''}` : ''}
    <div class="tiny muted">⏱ ${q.time}s</div></div>`;

  const draw = () => mount(root, html`
    <div class="row between mb"><div><a href="#/exams" class="small">← ${t('back_to_exams')}</a><h1>${r.exam_title} ${r.is_practice ? html`<span class="chip info">${t('practice')}</span>` : ''}</h1></div>
      <div class="row">
        <button class="btn" data-dl="report">⬇ ${t('download_report')}</button>
        ${r.certificate_available ? html`<button class="btn primary" data-dl="cert">🎓 ${t('download_certificate')}</button>` : ''}
        ${r.is_practice ? html`<a class="btn" href="#/exam/${r.exam_id}?practice=1">${t('practice_again')}</a>` : ''}
        ${r.rank ? html`<a class="btn" href="#/leaderboard/${r.exam_id}">${t('leaderboard')}</a>` : ''}</div></div>
    ${note ? html`<div class="banner warn">${note}</div>` : ''}
    <div class="card row" style="gap:1.5rem">
      <div class="score-ring" style="--p:${r.percent};--c:${c}" role="img" aria-label="${fmtNum(r.percent, 1)}%"><div><b>${fmtNum(r.percent, 1)}%</b><span class="small muted">${fmtNum(r.score)} / ${fmtNum(r.max_score)}</span></div></div>
      <div class="grow"><h2 style="color:${c}">${pass ? t('passed') : t('failed')}</h2><p class="muted">${t('pass_mark_is', { n: r.pass_percent })}</p>
        <div class="grid g4"><div class="stat"><b style="color:var(--ok)">${r.correct}</b><span>${t('correct')}</span></div><div class="stat"><b style="color:var(--bad)">${r.wrong}</b><span>${t('wrong')}</span></div>
          <div class="stat"><b>${r.unanswered}</b><span>${t('unanswered')}</span></div><div class="stat"><b>${fmtDur(r.seconds)}</b><span>${t('time_taken')}</span></div>
          ${r.rank ? html`<div class="stat"><b>#${r.rank.position}</b><span>${t('rank_of', { n: r.rank.of })}</span></div>` : ''}</div></div></div>
    ${topics.length || secs.length ? html`<div class="grid g2 mt">${topics.length ? html`<div class="card"><h3>${t('topic_perf')}</h3>${hBars(topics)}<p class="tiny muted">${t('weakest_first')}</p></div>` : ''}
      ${secs.length ? html`<div class="card"><h3>${t('section_perf')}</h3>${hBars(secs)}</div>` : ''}</div>` : ''}
    <div class="card mt"><div class="row between"><h2>${t('review')}</h2><label class="inline"><input type="checkbox" id="ow" ${onlyWrong ? 'checked' : ''}> ${t('show_wrong_only')}</label></div>
      ${(r.review || []).map((q, i) => ({ q, i })).filter(({ q }) => !onlyWrong || q.status !== 'correct').map(({ q, i }) => reviewItem(q, i + 1))}
      ${!r.answers_revealed ? html`<p class="muted small">${t('answers_hidden_note')}</p>` : ''}</div>`);
  draw();
  on(root, 'click', '[data-dl]', async (e, el) => {
    try { await download(el.dataset.dl === 'cert' ? `/api/attempts/${id}/certificate.pdf` : `/api/attempts/${id}/report.pdf`, 'report.pdf'); } catch (er) { toast(er.message, 'bad'); }
  });
  on(root, 'change', '#ow', (e) => { onlyWrong = e.target.checked; draw(); });
}
