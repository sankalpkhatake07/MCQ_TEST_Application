import { api } from '../api.js';
import { t, setLang, LANGS } from '../i18n.js';
import { getPrefs } from '../store.js';
import { checkCamera } from '../proctor.js';
import { fmtDate, html, mount, statusChip, toast } from '../ui.js';

export default async function instructions({ root, params, go, query }) {
  const id = params[0], practice = query.get('practice') === '1';
  const e = await api(`/api/exams/${id}`);
  const isStaff = e.sections !== undefined;                        // staff get the management view of the same endpoint
  if (e.languages && !e.languages.includes(getPrefs().lang)) await setLang(e.languages[0]);
  let stream = null, camOk = !(e.camera_required && !practice), busy = false;
  const proctored = !practice && !isStaff;
  const rules = [
    [true, t('rule_autosave')], [e.negative_mark > 0, t('rule_negative', { n: e.negative_mark })], [e.shuffle_questions || e.shuffle_options, t('rule_shuffle')],
    [proctored && e.lockdown, t('rule_lockdown')], [proctored && e.fullscreen_required, t('rule_fullscreen')],
    [proctored && e.camera_required, t('rule_camera')], [proctored && e.mic_enabled, t('rule_mic')], [proctored && e.ai_proctoring, t('rule_ai')],
    [proctored, t('rule_tabs')], [e.pass_percent, t('rule_pass', { n: e.pass_percent })],
  ].filter(([c]) => c);
  const existing = e.my_attempt && e.my_attempt.status !== 'submitted';

  const draw = () => mount(root, html`
    <div class="row between mb"><div><a href="#/exams" class="small">← ${t('back_to_exams')}</a><h1>${e.title}${practice ? html` <span class="chip info">${t('practice')}</span>` : ''}</h1></div>
      <span class="chip ${statusChip(e.status)}">${t('status_' + e.status)}</span></div>
    <div class="grid g2">
      <section class="card"><h2>${t('instructions')}</h2>
        ${e.description ? html`<p>${e.description}</p>` : ''}
        ${e.instructions ? html`<p style="white-space:pre-wrap">${e.instructions}</p>` : ''}
        <dl class="kv mt"><dt>${t('duration')}</dt><dd>${t('minutes_n', { n: e.duration_min })}</dd><dt>${t('questions')}</dt><dd>${e.question_count ?? e.questions?.length ?? '—'}</dd>
          ${e.start_at ? html`<dt>${t('opens')}</dt><dd>${fmtDate(e.start_at)}</dd>` : ''}${e.end_at ? html`<dt>${t('closes')}</dt><dd>${fmtDate(e.end_at)}</dd>` : ''}</dl>
        <h3 class="mt">${t('rules')}</h3><ul>${rules.map(([, txt]) => html`<li>${txt}</li>`)}</ul></section>
      <section class="card"><h2>${t('before_you_begin')}</h2>
        ${e.languages?.length > 1 ? html`<label for="lg">${t('choose_language')}</label><select id="lg">${e.languages.map((l) => html`<option value="${l}" ${l === getPrefs().lang ? 'selected' : ''}>${LANGS[l] || l}</option>`)}</select>` : ''}
        ${proctored && e.camera_required ? html`<h3 class="mt">${t('camera_check')}</h3>
          <div class="row"><div class="preview"><video id="pv" muted playsinline autoplay></video></div>
          <div class="col"><button class="btn" id="cam">${t('check_camera')}</button><span class="small ${camOk ? '' : 'muted'}" id="camst">${camOk ? '✓ ' + t('camera_ok') : t('camera_needed')}</span></div></div>` : ''}
        <label class="inline mt"><input type="checkbox" id="agree"> <span>${t('i_agree')}</span></label>
        <div class="banner bad small hidden" id="err" role="alert"></div>
        <div class="row mt"><button class="btn primary" id="go" disabled>${existing ? t('resume_exam') : t('begin')}</button></div></section>
    </div>`);

  const refresh = () => { const b = root.querySelector('#go'); b.disabled = busy || !root.querySelector('#agree').checked || !camOk; };
  const err = (m) => { const el = root.querySelector('#err'); el.textContent = m; el.classList.remove('hidden'); };
  draw();
  root.querySelector('#agree').onchange = refresh;
  root.querySelector('#lg')?.addEventListener('change', async (ev) => { await setLang(ev.target.value); draw(); wire(); });
  function wire() {
    root.querySelector('#agree').onchange = refresh;
    root.querySelector('#lg')?.addEventListener('change', async (ev) => { await setLang(ev.target.value); draw(); wire(); });
    root.querySelector('#cam')?.addEventListener('click', async () => {
      try { stream?.getTracks().forEach((x) => x.stop()); stream = await checkCamera({ mic: e.mic_enabled }); const v = root.querySelector('#pv'); v.srcObject = stream; camOk = true; root.querySelector('#camst').textContent = '✓ ' + t('camera_ok'); refresh(); }
      catch (ex) { camOk = false; root.querySelector('#camst').textContent = t('camera_fail'); refresh(); }
    });
    root.querySelector('#go').onclick = async () => {
      busy = true; refresh();
      try {
        if (proctored && e.fullscreen_required) await document.documentElement.requestFullscreen?.().catch(() => {});   // needs this click as the user gesture
        stream?.getTracks().forEach((x) => x.stop());
        const r = await api(`/api/exams/${id}/start${practice || isStaff ? '?practice=true' : ''}`, { method: 'POST', quiet: true });
        go(`/take/${r.attempt_id}`);
      } catch (ex) {
        busy = false; refresh();
        const d = String(ex.message);
        if (d.startsWith('already_submitted:')) return go(`/result/${d.split(':')[1]}`);
        if (d.startsWith('not_started:')) return err(t('not_started_yet', { when: fmtDate(d.slice(12)) }));
        err(d.startsWith('ip_not_allowed') ? t('ip_blocked') : d);
      }
    };
  }
  wire();
  return () => stream?.getTracks().forEach((x) => x.stop());
}
