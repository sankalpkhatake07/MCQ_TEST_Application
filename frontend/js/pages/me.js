import { api } from '../api.js';
import { t } from '../i18n.js';
import { fmtDate, fmtNum, hBars, html, lineChart, mount } from '../ui.js';

export default async function me({ root }) {
  const d = await api('/api/me/analytics');
  const topics = Object.entries(d.topics).map(([k, v]) => ({ label: k, value: Math.round(v.percent), sub: `${v.correct}/${v.total}` })).sort((a, b) => a.value - b.value);
  const weak = topics.filter((x) => x.value < 50).map((x) => x.label);
  mount(root, html`
    <h1>${t('my_progress')}</h1>
    ${d.attempts ? html`
      <div class="grid g4 mb"><div class="stat"><b>${d.attempts}</b><span>${t('attempts')}</span></div><div class="stat"><b>${fmtNum(d.average_percent, 1)}%</b><span>${t('avg_score')}</span></div><div class="stat"><b>${fmtNum(d.avg_time_per_question, 0)}s</b><span>${t('avg_time_q')}</span></div></div>
      ${weak.length ? html`<div class="banner warn"><b>${t('focus_on')}:</b> ${weak.join(', ')}</div>` : ''}
      <div class="grid g2"><div class="card charts"><div class="chart-title">${t('score_trend')}</div>${lineChart(d.trend.map((x) => ({ value: x.percent, label: x.exam, practice: x.practice })))}<p class="tiny muted">${t('trend_legend')}</p></div>
        <div class="card"><div class="chart-title">${t('topic_strength')}</div>${hBars(topics)}</div></div>
      <div class="card mt"><h3>${t('history')}</h3><div class="table-wrap"><table><thead><tr><th>${t('exam')}</th><th>%</th><th>${t('date')}</th><th></th></tr></thead><tbody>
        ${[...d.trend].reverse().map((x) => html`<tr><td>${x.exam} ${x.practice ? html`<span class="chip info">${t('practice')}</span>` : ''}</td><td>${fmtNum(x.percent, 1)}</td><td>${fmtDate(x.date)}</td><td><a class="btn sm" href="#/result/${x.attempt_id}">${t('view_result')}</a></td></tr>`)}</tbody></table></div></div>`
    : html`<div class="card empty"><h3>${t('no_attempts_yet')}</h3><a class="btn primary" href="#/exams">${t('my_exams')}</a></div>`}`);
}
