import { api, auth } from '../api.js';
import { t } from '../i18n.js';
import { fmtDur, fmtNum, html, mount } from '../ui.js';

export default async function leaderboard({ root, params }) {
  const id = params[0];
  let es = null, closed = false, timer = null;
  const load = async () => {
    const d = await api(`/api/exams/${id}/leaderboard`);
    mount(root, html`
      <div class="row between mb"><div><a href="javascript:history.back()" class="small">← ${t('back')}</a><h1>${t('leaderboard')} — ${d.title}</h1></div><span class="chip ok"><span class="live-dot"></span>${t('live')}</span></div>
      ${d.me ? html`<div class="banner ok"><b>${t('your_rank')}: #${d.me.rank}</b> · ${fmtNum(d.me.score)} / ${fmtNum(d.me.max_score)}</div>` : ''}
      <div class="card"><div class="table-wrap"><table><thead><tr><th>#</th><th>${t('name')}</th><th>${t('score')}</th><th>%</th><th>${t('time_taken')}</th></tr></thead><tbody>
        ${d.rows.length ? d.rows.map((r) => html`<tr ${r.user_id === auth.user.id ? 'style="font-weight:700;background:var(--accent-soft)"' : ''}><td>${r.rank <= 3 ? ['🥇', '🥈', '🥉'][r.rank - 1] : r.rank}</td><td>${r.name}</td><td>${fmtNum(r.score)} / ${fmtNum(r.max_score)}</td><td>${fmtNum(r.percent, 1)}</td><td>${fmtDur(r.seconds)}</td></tr>`)
          : html`<tr><td colspan="5" class="empty">${t('no_results_yet')}</td></tr>`}</tbody></table></div></div>`);
  };
  await load();
  async function connect() {
    if (closed) return;
    try {
      const { ticket } = await api(`/api/live/ticket/${id}?kind=rank`, { method: 'POST', quiet: true });
      es = new EventSource(`/api/live/stream?t=${encodeURIComponent(ticket)}`);
      es.onmessage = (m) => { try { if (JSON.parse(m.data).type === 'rank') load(); } catch { /* ignore */ } };
      es.onerror = () => { es.close(); timer = setTimeout(connect, 5000); };     // ticket is short-lived: fetch a new one on reconnect
    } catch { timer = setTimeout(connect, 8000); }
  }
  connect();
  return () => { closed = true; es?.close(); clearTimeout(timer); };
}
