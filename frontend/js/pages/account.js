import { api, auth } from '../api.js';
import { t, LANGS, setLang } from '../i18n.js';
import { getPrefs, setPref } from '../store.js';
import { html, mount, on, toast } from '../ui.js';

export default async function account({ root }) {
  let u = await api('/api/auth/me'); auth.setUser(u);
  const p = getPrefs();
  const draw = () => mount(root, html`
    <h1>${t('account')}</h1>
    <div class="grid g2">
      <section class="card"><h2>${t('profile')}</h2><dl class="kv"><dt>${t('name')}</dt><dd>${u.name || '—'}</dd><dt>${t('email')}</dt><dd>${u.email}</dd><dt>Role</dt><dd>${u.role}</dd>${u.roll_no ? html`<dt>Roll no</dt><dd>${u.roll_no}</dd>` : ''}</dl></section>
      <section class="card"><h2>${t('appearance')}</h2>
        <label for="th">${t('theme')}</label><select id="th">${['auto', 'light', 'dark'].map((x) => html`<option value="${x}" ${x === p.theme ? 'selected' : ''}>${t('theme_' + x)}</option>`)}</select>
        <label for="lg">${t('language')}</label><select id="lg">${Object.entries(LANGS).map(([k, v]) => html`<option value="${k}" ${k === getPrefs().lang ? 'selected' : ''}>${v}</option>`)}</select>
        <label for="fs">${t('text_size')}: <span id="fsv">${Math.round(getPrefs().fs * 100)}%</span></label><input id="fs" type="range" min="0.85" max="1.5" step="0.05" value="${getPrefs().fs}">
        <label class="inline"><input type="checkbox" id="hc" ${p.contrast === 'high' ? 'checked' : ''}> ${t('high_contrast')}</label></section>
      <section class="card"><h2>${t('security')}</h2>
        <form id="pwf" novalidate>${u.has_password ? html`<label for="cp">${t('current_password')}</label><input id="cp" type="password" autocomplete="current-password">` : ''}
          <label for="np">${t('new_password')}</label><input id="np" type="password" autocomplete="new-password"><p class="hint">${t('password_rule')}</p>
          <button class="btn mt">${u.has_password ? t('change_password') : t('set_password')}</button></form>
        <hr style="border:0;border-top:1px solid var(--line);margin:1rem 0">
        <label class="inline"><input type="checkbox" id="mfa" ${u.mfa_enabled ? 'checked' : ''}> <span><b>${t('mfa')}</b><br><span class="muted small">${t('mfa_hint')}</span></span></label></section>
    </div>`);
  draw();
  on(root, 'change', '#th', (e) => setPref('theme', e.target.value));
  on(root, 'change', '#lg', async (e) => { await setLang(e.target.value); draw(); });
  on(root, 'input', '#fs', (e) => { setPref('fs', +e.target.value); document.getElementById('fsv').textContent = Math.round(e.target.value * 100) + '%'; });
  on(root, 'change', '#hc', (e) => setPref('contrast', e.target.checked ? 'high' : 'normal'));
  on(root, 'submit', '#pwf', async (e) => {
    e.preventDefault();
    try { await api('/api/auth/set-password', { method: 'POST', body: { password: root.querySelector('#np').value, current_password: root.querySelector('#cp')?.value || null } }); toast(t('saved_ok'), 'ok'); u = await api('/api/auth/me'); auth.setUser(u); draw(); }
    catch (er) { toast(er.message, 'bad'); }
  });
  on(root, 'change', '#mfa', async (e) => {
    try { u = await api('/api/auth/mfa', { method: 'POST', body: { enabled: e.target.checked } }); auth.setUser(u); toast(t('saved_ok'), 'ok'); } catch (er) { e.target.checked = !e.target.checked; toast(er.message, 'bad'); }
  });
}
