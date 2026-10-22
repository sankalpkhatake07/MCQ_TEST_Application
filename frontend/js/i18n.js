// Tiny i18n: JSON dictionaries in /i18n, English fallback, {placeholders}. Add a language = add a JSON file.
import { getPrefs, setPref } from './store.js';
export const LANGS = { en: 'English', hi: 'हिन्दी', mr: 'मराठी' };
let dict = {}, fallback = {};
const cache = {};
async function load(l) { if (!cache[l]) { try { cache[l] = await (await fetch(`/i18n/${l}.json`)).json(); } catch { cache[l] = {}; } } return cache[l]; }
export async function initI18n() { fallback = await load('en'); dict = await load(getPrefs().lang); }
export async function setLang(l) { if (!LANGS[l]) l = 'en'; dict = await load(l); setPref('lang', l); }
export function t(key, vars) {
  let s = dict[key] ?? fallback[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  return s;
}
