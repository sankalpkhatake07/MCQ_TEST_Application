// Small UI toolkit: auto-escaping html`` templates, toasts, modals, formatting, SVG charts.
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ESC[c]);

class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(String(s ?? ''));
const val = (v) => v instanceof Raw ? v.s : Array.isArray(v) ? v.map(val).join('') : (v === false || v == null) ? '' : esc(v);
/** Tagged template: every ${value} is HTML-escaped unless wrapped in raw() or produced by another html``. */
export function html(strings, ...vals) {
  let out = '';
  strings.forEach((s, i) => { out += s; if (i < vals.length) out += val(vals[i]); });
  return new Raw(out);
}
export const mount = (el, tpl) => { el.innerHTML = tpl instanceof Raw ? tpl.s : String(tpl); return el; };

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** Event delegation: on(root,'click','[data-act]', (e, el) => ...). Returns an unsubscribe function. */
export function on(root, type, selector, handler) {
  const fn = (e) => { const el = e.target.closest(selector); if (el && root.contains(el)) handler(e, el); };
  root.addEventListener(type, fn);
  return () => root.removeEventListener(type, fn);
}

// ---------------------------------------------------------------- sanitiser (defence in depth; server also sanitises)
const OK_TAGS = new Set(['P', 'BR', 'B', 'STRONG', 'I', 'EM', 'U', 'S', 'SUB', 'SUP', 'UL', 'OL', 'LI', 'CODE', 'PRE', 'BLOCKQUOTE', 'H3', 'H4', 'SPAN', 'DIV', 'IMG']);
export function sanitizeHtml(src) {
  const doc = new DOMParser().parseFromString(`<body>${src || ''}</body>`, 'text/html');
  const walk = (node) => {
    [...node.childNodes].forEach((ch) => {
      if (ch.nodeType === 3) return;
      if (ch.nodeType !== 1 || !OK_TAGS.has(ch.tagName)) { ch.remove(); return; }
      [...ch.attributes].forEach((a) => {
        const keep = ch.tagName === 'IMG' && (a.name === 'alt' || a.name === 'width' || a.name === 'height' || (a.name === 'src' && /^\/api\/media\/[a-f0-9]{32}\.\w+$/.test(a.value)))
          || (a.name === 'class' && /^language-[\w+#-]+$/.test(a.value));
        if (!keep) ch.removeAttribute(a.name);
      });
      if (ch.tagName === 'IMG' && !ch.getAttribute('src')) { ch.remove(); return; }
      walk(ch);
    });
  };
  walk(doc.body);
  return doc.body.innerHTML;
}
export const rich = (src) => raw(sanitizeHtml(src));
export const stripTags = (s) => { const d = document.createElement('div'); d.innerHTML = sanitizeHtml(s); return d.textContent.replace(/\s+/g, ' ').trim(); };

// ---------------------------------------------------------------- toasts & modals
export function toast(msg, kind = '') {
  const t = document.createElement('div');
  t.className = `toast ${kind}`; t.textContent = msg; t.setAttribute('role', 'status');
  document.getElementById('toasts').appendChild(t);
  setTimeout(() => t.remove(), kind === 'bad' ? 6500 : 3500);
}

/** Opens a modal. Returns {el, close}. `body` is html``; wire events on `el` in onOpen. */
export function openModal({ title, body, wide = false, onOpen }) {
  const root = document.getElementById('modal-root');
  const back = document.createElement('div');
  back.className = 'modal-back';
  back.innerHTML = `<div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}"><h2>${esc(title)}</h2><div class="modal-body"></div></div>`;
  root.appendChild(back);
  const prev = document.activeElement;
  const box = back.querySelector('.modal');
  mount(back.querySelector('.modal-body'), body);
  const close = (v) => { back.remove(); document.removeEventListener('keydown', onKey); prev?.focus?.(); api.resolve?.(v); };
  const api = { el: box, close, resolve: null };
  const onKey = (e) => { if (e.key === 'Escape') close(null); };
  document.addEventListener('keydown', onKey);
  back.addEventListener('mousedown', (e) => { if (e.target === back) close(null); });
  (box.querySelector('[autofocus]') || box.querySelector('input,select,textarea,button'))?.focus();
  onOpen?.(box, close);
  return api;
}

export function confirmDialog(message, { okText = 'Confirm', danger = false, title = 'Are you sure?' } = {}) {
  return new Promise((resolve) => {
    const m = openModal({ title, body: html`<p>${message}</p><div class="actions"><button class="btn" data-no>Cancel</button><button class="btn ${danger ? 'danger solid' : 'primary'}" data-yes>${okText}</button></div>`,
      onOpen: (el, close) => { el.querySelector('[data-no]').onclick = () => close(false); el.querySelector('[data-yes]').onclick = () => close(true); } });
    m.resolve = resolve;
  });
}

/** Form modal: fields are rendered by caller; returns promise of the value returned by onSubmit(el) or null. */
export function formModal({ title, body, submitText = 'Save', wide = false, onSubmit, onReady }) {
  return new Promise((resolve) => {
    const m = openModal({ title, wide, body: html`<form novalidate>${body}<div class="actions"><button type="button" class="btn" data-cancel>Cancel</button><button class="btn primary" type="submit">${submitText}</button></div><div class="banner bad hidden" data-err role="alert"></div></form>`,
      onOpen: (el, close) => {
        const form = el.querySelector('form'), err = el.querySelector('[data-err]'), btn = form.querySelector('[type=submit]');
        el.querySelector('[data-cancel]').onclick = () => close(null);
        onReady?.(form, el);
        form.onsubmit = async (e) => {
          e.preventDefault(); err.classList.add('hidden'); btn.disabled = true;
          try { const v = await onSubmit(form); if (v !== false) close(v ?? true); }
          catch (ex) { err.textContent = ex.message || String(ex); err.classList.remove('hidden'); }
          finally { btn.disabled = false; }
        };
      } });
    m.resolve = resolve;
  });
}

// ---------------------------------------------------------------- formatting
export const pad = (n) => String(n).padStart(2, '0');
export function fmtClock(sec) { sec = Math.max(0, Math.floor(sec)); const h = Math.floor(sec / 3600); return (h ? `${h}:${pad(Math.floor(sec % 3600 / 60))}` : `${pad(Math.floor(sec / 60))}`) + `:${pad(sec % 60)}`; }
export function fmtDur(sec) { sec = Math.round(sec || 0); return sec >= 3600 ? `${Math.floor(sec / 3600)}h ${Math.floor(sec % 3600 / 60)}m` : `${Math.floor(sec / 60)}m ${pad(sec % 60)}s`; }
export function fmtDate(iso, withTime = true) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString(undefined, withTime ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' });
}
export const fmtNum = (n, d = 2) => (n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));
/** <input type=datetime-local> value (local time) from an ISO UTC string, and back. */
export function toLocalInput(iso) { if (!iso) return ''; const d = new Date(iso); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }
export function fromLocalInput(v) { return v ? new Date(v).toISOString() : ''; }
export const statusChip = (s) => ({ open: 'ok', upcoming: 'info', closed: '', draft: 'warn', submitted: 'ok', in_progress: 'info', paused: 'warn' }[s] ?? '');

// ---------------------------------------------------------------- SVG charts (theme aware via CSS variables)
const niceMax = (v) => { if (v <= 4) return 4; if (v <= 10) return Math.ceil(v / 2) * 2; const p = 10 ** Math.floor(Math.log10(v)); return Math.ceil(v / p) * p; };
export function barChart(items, { height = 190, max, unit = '', colors } = {}) {
  const W = 560, H = height, pl = 34, pb = 26, pt = 10, n = items.length || 1;
  const top = max ?? niceMax(Math.max(1, ...items.map((i) => i.value)));
  const bw = (W - pl - 8) / n, ch = H - pb - pt;
  const grid = [0, .5, 1].map((f) => { const y = pt + ch - f * ch; return `<line x1="${pl}" x2="${W}" y1="${y}" y2="${y}" stroke="var(--line)"/><text x="${pl - 6}" y="${y + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${Math.round(top * f)}</text>`; }).join('');
  const bars = items.map((it, i) => {
    const h = Math.max(it.value ? 2 : 0, it.value / top * ch), x = pl + i * bw + bw * .15, w = bw * .7, y = pt + ch - h;
    const c = it.color || colors?.[i] || 'var(--accent)';
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3" fill="${c}"><title>${esc(it.label)}: ${it.value}${unit}</title></rect>
      <text x="${x + w / 2}" y="${H - 8}" text-anchor="middle" font-size="${n > 12 ? 9 : 11}" fill="var(--muted)">${esc(String(it.label).slice(0, 10))}</text>
      ${it.value && n <= 14 ? `<text x="${x + w / 2}" y="${y - 3}" text-anchor="middle" font-size="10" fill="var(--text)">${it.value}</text>` : ''}`;
  }).join('');
  return raw(`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Bar chart">${grid}${bars}</svg>`);
}
export function hBars(items, { max = 100, unit = '%' } = {}) {
  return html`${items.map((i) => html`<div class="mb"><div class="row between small"><span>${i.label}</span><b>${i.value}${unit}</b></div>
    <div class="bar ${i.value >= 70 ? 'ok' : i.value >= 40 ? '' : 'bad'}" role="progressbar" aria-valuenow="${i.value}" aria-valuemin="0" aria-valuemax="${max}"><i style="width:${Math.min(100, i.value / max * 100)}%"></i></div>
    ${i.sub ? html`<div class="tiny muted">${i.sub}</div>` : ''}</div>`)}`;
}
export function lineChart(points, { height = 200, max = 100 } = {}) {
  const W = 560, H = height, pl = 34, pb = 26, pt = 12, n = points.length;
  if (!n) return raw('');
  const cw = W - pl - 14, ch = H - pb - pt, x = (i) => pl + (n === 1 ? cw / 2 : i / (n - 1) * cw), y = (v) => pt + ch - Math.min(max, v) / max * ch;
  const grid = [0, 25, 50, 75, 100].map((g) => `<line x1="${pl}" x2="${W}" y1="${y(g)}" y2="${y(g)}" stroke="var(--line)"/><text x="${pl - 6}" y="${y(g) + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${g}</text>`).join('');
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.value)}`).join(' ');
  const dots = points.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.value)}" r="4.5" fill="${p.practice ? 'var(--surface)' : 'var(--accent)'}" stroke="var(--accent)" stroke-width="2"><title>${esc(p.label)}: ${p.value}%</title></circle>`).join('');
  return raw(`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Score trend">${grid}<path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2.5"/>${dots}</svg>`);
}
export function donut(parts, { size = 150 } = {}) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1, R = 52, C = 2 * Math.PI * R;
  let off = 0;
  const arcs = parts.map((p) => { const len = p.value / total * C; const s = `<circle r="${R}" cx="70" cy="70" fill="none" stroke="${p.color}" stroke-width="18" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 70 70)"><title>${esc(p.label)}: ${p.value}</title></circle>`; off += len; return s; }).join('');
  return raw(`<svg viewBox="0 0 140 140" width="${size}" height="${size}" role="img" aria-label="Donut chart"><circle r="${R}" cx="70" cy="70" fill="none" stroke="var(--surface-2)" stroke-width="18"/>${arcs}<text x="70" y="75" text-anchor="middle" font-size="20" font-weight="700" fill="var(--text)">${total === 1 && !parts.some((p) => p.value) ? 0 : parts.reduce((a, p) => a + p.value, 0)}</text></svg>`);
}
