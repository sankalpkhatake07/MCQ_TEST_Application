import { api } from '../api.js';
import { t } from '../i18n.js';
import { fmtDate, html, mount, on, statusChip, toast } from '../ui.js';

export default async function studentHome({ root, go }) {
  const exams = await api('/api/exams');
  const card = (e) => {
    const a = e.my_attempt;
    let action;
    if (a && a.status === 'submitted') action = html`<a class="btn primary" href="#/result/${a.id}">${t('view_result')}</a>`;
    else if (a) action = html`<a class="btn primary" href="#/exam/${e.id}">${t('resume_exam')}</a>`;
    else if (e.status === 'open') action = html`<a class="btn primary" href="#/exam/${e.id}">${t('start_exam')}</a>`;
    else if (e.status === 'upcoming') action = html`<span class="chip info">${t('opens_at', { when: fmtDate(e.start_at) })}</span>`;
    else action = html`<span class="chip">${t('status_closed')}</span>`;
    return html`<article class="card exam-card">
      <div class="row between"><h3>${e.title}</h3><span class="chip ${statusChip(e.status)}">${t('status_' + e.status)}</span></div>
      <p class="muted small">${e.description || ''}</p>
      <div class="row small muted"><span>⏱ ${t('minutes_n', { n: e.duration_min })}</span>${e.negative_mark ? html`<span>− ${t('negative_marking')} ${e.negative_mark}</span>` : ''}${e.end_at ? html`<span>${t('closes_at', { when: fmtDate(e.end_at) })}</span>` : ''}</div>
      <div class="row mt">${action}
        ${e.can_practice ? html`<a class="btn" href="#/exam/${e.id}?practice=1">${t('practice')}</a>` : ''}
        ${e.live_ranking && (a?.status === 'submitted' || e.status === 'closed') ? html`<a class="btn" href="#/leaderboard/${e.id}">${t('leaderboard')}</a>` : ''}</div></article>`;
  };
  mount(root, html`
    <div class="row between mb"><h1>${t('my_exams')}</h1>
      <form id="join" class="row"><label class="sr-only" for="jid">${t('exam_id')}</label><input id="jid" inputmode="numeric" placeholder="${t('exam_id')}" style="width:140px" required><button class="btn">${t('join')}</button></form></div>
    ${exams.length ? html`<div class="grid g2">${exams.map(card)}</div>` : html`<div class="card empty"><h3>${t('no_exams')}</h3><p>${t('no_exams_hint')}</p></div>`}`);
  root.querySelector('#join').onsubmit = (e) => { e.preventDefault(); const v = root.querySelector('#jid').value.trim(); if (/^\d+$/.test(v)) go(`/exam/${v}`); else toast(t('exam_id_invalid'), 'bad'); };
}
