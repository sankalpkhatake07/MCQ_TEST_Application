// Shell + hash router. Pages live in /js/pages and export `default async (ctx) => cleanup?`.
import { api, auth } from './api.js';
import { initI18n, t, LANGS, setLang } from './i18n.js';
import { getPrefs, setPref, bumpFont, onPref } from './store.js';
import { $, html, mount, on, toast } from './ui.js';

const root = document.getElementById('main');
const shell = document.getElementById('shell');
let cleanup = null, navToken = 0, publicCfg = null;

const ROUTES = [
  [/^\/login$/, 'login', { public: true }],
  [/^\/exams$/, 'student-home'],
  [/^\/exam\/(\d+)$/, 'instructions'],
  [/^\/take\/(\d+)$/, 'take', { exam: true }],
  [/^\/result\/(\d+)$/, 'result'],
  [/^\/leaderboard\/(\d+)$/, 'leaderboard'],
  [/^\/me$/, 'me'],
  [/^\/account$/, 'account'],
  [/^\/teacher$/, 'teacher', { staff: true }],
  [/^\/teacher\/exam\/(\d+)$/, 'exam-editor', { staff: true }],
  [/^\/teacher\/exam\/(\d+)\/results$/, 'exam-results', { staff: true }],
  [/^\/teacher\/attempt\/(\d+)$/, 'attempt-detail', { staff: true }],
  [/^\/bank$/, 'bank', { staff: true }],
  [/^\/students$/, 'students', { staff: true }],
  [/^\/admin$/, 'admin', { admin: true }],
];

export const go = (path) => { if (location.hash === '#' + path) route(); else location.hash = path; };
export const getConfig = async () => (publicCfg ??= await api('/api/auth/config', { quiet: true }).catch(() => ({ languages: LANGS })));
export const homeFor = (u) => (u && u.role === 'student' ? '/exams' : '/teacher');

function renderShell(path) {
  const u = auth.user, p = getPrefs();
  const staff = u && (u.role === 'teacher' || u.role === 'admin');
  const link = (href, label, match) => html`<a href="#${href}" ${path.startsWith(match || href) ? 'aria-current="page"' : ''}>${label}</a>`;
  mount(shell, html`
    <a class="brand" href="#${u ? homeFor(u) : '/login'}"><span class="mark"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7"/></svg></span>${t('app_name')}</a>
    ${u ? html`<nav class="nav" aria-label="Main">
      ${u.role === 'student' ? html`${link('/exams', t('my_exams'))}${link('/me', t('my_progress'))}` : ''}
      ${staff ? html`${link('/teacher', 'Exams')}${link('/bank', 'Question bank')}${link('/students', 'Students')}` : ''}
      ${u.role === 'admin' ? link('/admin', 'Admin') : ''}
    </nav>` : ''}
    <div class="tools" role="group" aria-label="Display settings">
      <label class="hidden" for="lang-sel">Language</label>
      <select id="lang-sel" aria-label="Language">${Object.entries(LANGS).map(([k, v]) => html`<option value="${k}" ${k === p.lang ? 'selected' : ''}>${v}</option>`)}</select>
      <button class="btn sm icon" data-a="font-" title="Smaller text" aria-label="Decrease text size">A−</button>
      <button class="btn sm icon" data-a="font+" title="Larger text" aria-label="Increase text size">A+</button>
      <button class="btn sm icon" data-a="contrast" title="High contrast" aria-pressed="${p.contrast === 'high'}" aria-label="Toggle high contrast">◐</button>
      <button class="btn sm icon" data-a="theme" title="Theme: ${p.theme}" aria-label="Switch theme (${p.theme})">${p.theme === 'dark' ? '☾' : p.theme === 'light' ? '☀' : '◑'}</button>
      ${u ? html`<a class="btn sm who" href="#/account" title="Account">${u.name || u.email}</a><button class="btn sm who" data-a="logout">${t('sign_out')}</button>` : ''}
    </div>`);
}

on(shell, 'click', '[data-a]', async (e, el) => {
  const a = el.dataset.a, p = getPrefs();
  if (a === 'font+') bumpFont(0.1);
  else if (a === 'font-') bumpFont(-0.1);
  else if (a === 'contrast') setPref('contrast', p.contrast === 'high' ? 'normal' : 'high');
  else if (a === 'theme') setPref('theme', { auto: 'light', light: 'dark', dark: 'auto' }[p.theme]);
  else if (a === 'logout') { await api('/api/auth/logout', { method: 'POST', quiet: true }).catch(() => {}); auth.clear(); go('/login'); }
});
shell.addEventListener('change', async (e) => { if (e.target.id === 'lang-sel') {
  await setLang(e.target.value); renderShell(currentPath());
  if (document.body.dataset.mode === 'exam') window.dispatchEvent(new Event('lang-changed')); else route();
} });
onPref((k) => { if (k !== 'lang') renderShell(currentPath()); });

const currentPath = () => (location.hash.slice(1).split('?')[0] || '/');

async function route() {
  const token = ++navToken;
  const path = currentPath();
  if (cleanup) { try { await cleanup(); } catch (e) { console.warn(e); } cleanup = null; }
  document.body.dataset.mode = ''; document.body.classList.remove('lockdown');
  const u = auth.user;
  if (path === '/' || path === '') return go(u && auth.token ? homeFor(u) : '/login');
  const hit = ROUTES.map(([re, page, opt]) => [path.match(re), page, opt || {}]).find(([m]) => m);
  if (!hit) { mount(root, html`<div class="card empty"><h2>Page not found</h2><a class="btn" href="#/">Go home</a></div>`); renderShell(path); return; }
  const [m, page, opt] = hit;
  if (!opt.public && (!u || !auth.token)) return go('/login');
  if (opt.public && u && auth.token && path === '/login') return go(homeFor(u));
  if ((opt.staff && u.role === 'student') || (opt.admin && u.role !== 'admin')) { toast('You do not have access to that page', 'bad'); return go(homeFor(u)); }
  if (opt.exam) document.body.dataset.mode = 'exam';
  renderShell(path);
  // every page gets a fresh container, so its event listeners disappear with it
  const view = document.createElement('div');
  root.replaceChildren(view);
  mount(view, html`<p class="muted" role="status">${t('loading')}</p>`);
  try {
    const mod = await import(`./pages/${page}.js`);
    if (token !== navToken) return;
    mount(view, html``);
    const out = await mod.default({ root: view, params: m.slice(1), go, user: u, query: new URLSearchParams(location.hash.split('?')[1] || '') });
    if (token === navToken) cleanup = out || null; else if (out) out();
    root.focus({ preventScroll: true });
  } catch (err) {
    console.error(err);
    if (token === navToken) mount(view, html`<div class="card"><h2>Something went wrong</h2><p>${err.message}</p><button class="btn" onclick="location.reload()">Reload</button></div>`);
  }
}

window.addEventListener('hashchange', route);
window.addEventListener('auth-lost', (e) => {
  if (!auth.token) return;
  const replaced = e.detail === 'session_replaced';
  auth.clear();
  sessionStorage.setItem('examhub.notice', replaced ? t('session_replaced') : t('session_expired'));
  go('/login');
});

(async function boot() {
  await initI18n();
  await getConfig();
  if (auth.token) { try { auth.setUser(await api('/api/auth/me', { quiet: true })); } catch { auth.clear(); } }
  route();
})();
