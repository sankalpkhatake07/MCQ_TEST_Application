// Display preferences (theme, text size, contrast, language) persisted in localStorage.
const KEY = 'examhub.prefs';
const defaults = { theme: 'auto', contrast: 'normal', fs: 1, lang: 'en' };
let prefs = { ...defaults, ...(() => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } })() };
const listeners = new Set();
const mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

export const getPrefs = () => ({ ...prefs });
export function applyPrefs() {
  const dark = prefs.theme === 'dark' || (prefs.theme === 'auto' && mq && mq.matches);
  const r = document.documentElement;
  r.dataset.theme = dark ? 'dark' : 'light';
  r.dataset.contrast = prefs.contrast;
  r.style.setProperty('--fs', prefs.fs);
  r.lang = prefs.lang;
}
export function setPref(k, v) { prefs[k] = v; localStorage.setItem(KEY, JSON.stringify(prefs)); applyPrefs(); listeners.forEach((f) => f(k, v)); }
export const onPref = (f) => { listeners.add(f); return () => listeners.delete(f); };
export const bumpFont = (d) => setPref('fs', Math.min(1.5, Math.max(0.85, Math.round((prefs.fs + d) * 100) / 100)));
if (mq) mq.addEventListener?.('change', () => prefs.theme === 'auto' && applyPrefs());
applyPrefs();
