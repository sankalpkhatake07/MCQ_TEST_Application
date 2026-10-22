import { api, auth } from '../api.js';
import { getConfig, go, homeFor } from '../app.js';
import { t } from '../i18n.js';
import { $, html, mount, toast, esc } from '../ui.js';

export default async function login({ root }) {
  const cfg = await getConfig();
  const notice = sessionStorage.getItem('examhub.notice'); sessionStorage.removeItem('examhub.notice');
  let tab = 'otp', step = 'email', email = '', challenge = null, devOtp = null, busy = false, error = '';
  let msNonce = null;

  const draw = () => mount(root, html`
    <div class="auth"><div class="card auth-card">
      <div class="auth-side"><h1>${t('login_title')}</h1><p>${t('login_sub')}</p>
        <ul><li>${t('feat_autosave')}</li><li>${t('feat_langs')}</li><li>${t('feat_access')}</li></ul></div>
      <div class="auth-form">
        ${notice ? html`<div class="banner warn" role="alert">${notice}</div>` : ''}
        ${step === 'email' ? html`
          <div class="tabs" role="tablist"><button role="tab" aria-selected="${tab === 'otp'}" data-tab="otp">${t('email_code')}</button><button role="tab" aria-selected="${tab === 'pw'}" data-tab="pw">${t('password_login')}</button></div>
          <form id="f-email" novalidate>
            <label for="em">${t('email')}</label><input id="em" type="email" autocomplete="username" value="${email}" required autofocus>
            ${tab === 'pw' ? html`<label for="pw">${t('password')}</label><input id="pw" type="password" autocomplete="current-password" required>` : ''}
            ${tab === 'otp' && !cfg.allow_otp_only ? html`<p class="banner warn small">${t('otp_disabled')}</p>` : ''}
            <button class="btn primary mt" style="width:100%" ${busy ? 'disabled' : ''}>${tab === 'otp' ? t('send_code') : t('sign_in')}</button>
          </form>
          ${cfg.google_client_id || cfg.microsoft_client_id ? html`<div class="divider">${t('or_continue')}</div><div class="col">
            ${cfg.google_client_id ? html`<div id="g-btn"></div>` : ''}
            ${cfg.microsoft_client_id ? html`<button class="btn" id="ms-btn">${t('microsoft')}</button>` : ''}</div>` : ''}
        ` : html`
          <h2>${t('enter_code')}</h2><p class="muted">${t('code_sent', { email })}</p>
          ${devOtp ? html`<div class="banner ok small"><b>${t('dev_code')}:</b> <code>${devOtp}</code></div>` : ''}
          <form id="f-code" novalidate><label for="cd">${t('code')}</label>
            <input id="cd" inputmode="numeric" autocomplete="one-time-code" minlength="6" maxlength="6" pattern="[0-9]{6}" style="font-size:1.4rem;letter-spacing:.3em;text-align:center" required autofocus>
            <button class="btn primary mt" style="width:100%" ${busy ? 'disabled' : ''}>${t('verify')}</button></form>
          <button class="btn sm mt" id="back">${t('back')}</button>`}
        <div class="banner bad small ${error ? '' : 'hidden'}" role="alert" id="err">${error}</div>
      </div></div></div>`);

  const fail = (m) => { error = m; busy = false; draw(); wire(); };
  const finish = (r) => { auth.set(r.access, r.user); toast(t('welcome'), 'ok'); go(homeFor(r.user)); };
  const afterFirstFactor = (r) => { if (r.mfa_required) { challenge = r.challenge; devOtp = r.dev_otp || null; step = 'code'; busy = false; error = ''; draw(); wire(); } else finish(r); };

  async function googleInit() {
    if (!cfg.google_client_id) return;
    await new Promise((res) => { if (window.google?.accounts) return res(); const s = document.createElement('script'); s.src = 'https://accounts.google.com/gsi/client'; s.async = true; s.onload = res; s.onerror = res; document.head.appendChild(s); });
    if (!window.google?.accounts) return;
    window.google.accounts.id.initialize({ client_id: cfg.google_client_id, callback: async (resp) => {
      try { afterFirstFactor(await api('/api/auth/google', { method: 'POST', body: { id_token: resp.credential }, quiet: true })); } catch (e) { fail(e.message); } } });
    const host = $('#g-btn', root); if (host) window.google.accounts.id.renderButton(host, { theme: 'outline', size: 'large', text: 'continue_with', width: 280 });
  }
  function microsoft() {
    msNonce = crypto.getRandomValues(new Uint32Array(4)).join('');
    const redirect = location.origin + '/ms-callback.html';
    const url = `https://login.microsoftonline.com/${cfg.microsoft_tenant}/oauth2/v2.0/authorize?client_id=${cfg.microsoft_client_id}&response_type=id_token&redirect_uri=${encodeURIComponent(redirect)}&scope=openid%20email%20profile&response_mode=fragment&nonce=${msNonce}&prompt=select_account`;
    const w = window.open(url, 'ms-login', 'width=520,height=640');
    const handler = async (e) => {
      if (e.origin !== location.origin || e.data?.type !== 'ms-token') return;
      window.removeEventListener('message', handler); w?.close();
      try { afterFirstFactor(await api('/api/auth/microsoft', { method: 'POST', body: { id_token: e.data.token, nonce: msNonce }, quiet: true })); } catch (er) { fail(er.message); }
    };
    window.addEventListener('message', handler);
  }

  function wire() {
    root.querySelectorAll('[data-tab]').forEach((b) => b.onclick = () => { email = $('#em', root)?.value || email; tab = b.dataset.tab; error = ''; draw(); wire(); });
    $('#back', root)?.addEventListener('click', () => { step = 'email'; challenge = null; error = ''; draw(); wire(); });
    $('#ms-btn', root)?.addEventListener('click', microsoft);
    $('#f-email', root)?.addEventListener('submit', async (e) => {
      e.preventDefault(); email = $('#em', root).value.trim().toLowerCase(); busy = true; error = '';
      try {
        if (tab === 'otp') { const r = await api('/api/auth/request-otp', { method: 'POST', body: { email }, quiet: true }); devOtp = r.dev_otp || null; step = 'code'; challenge = null; busy = false; draw(); wire(); }
        else afterFirstFactor(await api('/api/auth/login', { method: 'POST', body: { email, password: $('#pw', root).value }, quiet: true }));
      } catch (er) { fail(er.message); }
    });
    $('#f-code', root)?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const code = $('#cd', root).value.trim();
      if (!/^\d{6}$/.test(code)) { fail(t('code_invalid')); return; }
      busy = true;
      try { finish(await api('/api/auth/verify-otp', { method: 'POST', body: { email, code, challenge }, quiet: true })); } catch (er) { fail(er.message); }
    });
    if (step === 'email') googleInit();
  }
  draw(); wire();
}
