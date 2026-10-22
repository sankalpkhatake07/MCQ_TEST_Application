// API client: bearer token, JSON/form helpers, server-clock sync, session-replaced handling.
const BASE = window.API_BASE || '';
const KEY = 'examhub.token', USER = 'examhub.user';

export const auth = {
  get token() { return localStorage.getItem(KEY); },
  get user() { try { return JSON.parse(localStorage.getItem(USER)); } catch { return null; } },
  set(token, user) { localStorage.setItem(KEY, token); localStorage.setItem(USER, JSON.stringify(user)); },
  setUser(user) { localStorage.setItem(USER, JSON.stringify(user)); },
  clear() { localStorage.removeItem(KEY); localStorage.removeItem(USER); },
};

export class ApiError extends Error {
  constructor(status, detail) { super(typeof detail === 'string' ? detail : (detail?.message || `Request failed (${status})`)); this.status = status; this.detail = detail; }
}

let offset = 0; // server time - client time (ms), so timers are right even if the PC clock is wrong
export const setServerTime = (iso) => { const t = Date.parse(iso); if (!Number.isNaN(t)) offset = t - Date.now(); };
export const serverNow = () => Date.now() + offset;

export async function api(path, { method = 'GET', body, form, headers = {}, quiet = false } = {}) {
  const h = { ...headers };
  if (auth.token) h.Authorization = `Bearer ${auth.token}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { h['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  let res;
  try { res = await fetch(BASE + path, { method, headers: h, body: payload }); }
  catch (e) { throw new ApiError(0, 'Cannot reach the server. Check your connection.'); }
  if (res.status === 204) return null;
  const isJson = (res.headers.get('content-type') || '').includes('json');
  const data = isJson ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    let detail = data?.detail ?? res.statusText;
    if (Array.isArray(detail)) detail = detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
    if (res.status === 401 && !quiet) window.dispatchEvent(new CustomEvent('auth-lost', { detail }));
    throw new ApiError(res.status, detail);
  }
  if (data && data.server_time) setServerTime(data.server_time);
  if (data && data.attempt && data.attempt.server_time) setServerTime(data.attempt.server_time);
  return data;
}

export async function download(path, fallbackName) {
  const res = await fetch(BASE + path, { headers: { Authorization: `Bearer ${auth.token}` } });
  if (!res.ok) { const d = await res.json().catch(() => ({})); throw new ApiError(res.status, d.detail || 'Download failed'); }
  const cd = res.headers.get('content-disposition') || '';
  const name = (cd.match(/filename="([^"]+)"/) || [])[1] || fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
