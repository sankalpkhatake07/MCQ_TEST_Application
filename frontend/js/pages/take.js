import { api, serverNow, setServerTime } from '../api.js';
import { t, setLang } from '../i18n.js';
import { getPrefs } from '../store.js';
import { Proctor } from '../proctor.js';
import { listSnapshots, queueSnapshot, removeSnapshots } from '../idb.js';
import { confirmDialog, fmtClock, html, mount, on, rich, toast, $, $$ } from '../ui.js';

const LETTERS = 'ABCDEFGH';

export default async function take({ root, params, go }) {
  const attemptId = +params[0];
  const QKEY = `examhub.q.${attemptId}`;
  let S = await api(`/api/attempts/${attemptId}/state`);
  if (S.submitted) return go(`/result/${attemptId}`);
  setServerTime(S.attempt.server_time);

  const practice = S.attempt.is_practice, exam = S.exam;
  const real = !practice;
  if (exam.languages && !exam.languages.includes(getPrefs().lang)) await setLang(exam.languages[0]);

  // ------------------------------------------------------------------ state
  let idx = 0, filter = 'all', saveState = 'saved', pending = 0, syncing = false, done = false;
  let expiresMs = Date.parse(S.attempt.expires_at), qStart = performance.now(), warnedMin = new Set();
  const local = { answers: { ...S.answers }, marked: new Set(S.marked), times: { ...S.times } };
  let Q = (() => { try { return JSON.parse(localStorage.getItem(QKEY)) || {}; } catch { return {}; } })();
  Q = { answers: Q.answers || {}, events: Q.events || [], offlineSince: Q.offlineSince || null };
  Object.entries(Q.answers).forEach(([qid, v]) => { local.answers[qid] = v.value; });   // unsent answers win over server copy
  const persist = () => localStorage.setItem(QKEY, JSON.stringify(Q));
  const timers = [], offs = [];
  let chain = Promise.resolve(), proctor = null, fsLocked = false, camLocked = false, fillTimer = null, warning = '';

  const questions = () => S.questions;
  const cur = () => questions()[idx];
  const answered = (q) => { const v = local.answers[q.id]; return v !== undefined && v !== null && String(v).trim() !== ''; };
  const sectionOf = (q) => S.sections.find((s) => s.id === q.section_id);
  const activeSection = () => S.sections.find((s) => s.status === 'active');

  // ------------------------------------------------------------------ skeleton
  document.body.classList.toggle('lockdown', real && exam.lockdown);
  mount(root, html`
    <div class="exam-bar" id="bar"></div>
    <div id="body"></div>
    <div class="pcam hidden" id="pcam" aria-label="Camera preview"></div>
    <div class="sr-only" role="status" aria-live="polite" id="live"></div>
    <div id="ov"></div>`);
  const bar = $('#bar', root), body = $('#body', root), ov = $('#ov', root), live = $('#live', root);

  // ------------------------------------------------------------------ rendering
  function drawBar() {
    const total = questions().length, ans = questions().filter(answered).length;
    mount(bar, html`
      <div class="grow"><strong>${exam.title}</strong> ${practice ? html`<span class="chip info">${t('practice')}</span>` : ''}
        <div class="tiny muted">${t('progress', { a: ans, n: S.exam.total_questions })}</div></div>
      ${S.attempt.timed_sections && activeSection() ? html`<div class="tiny muted">${activeSection().name}<div class="timer low" id="stimer" style="font-size:1.1rem;min-width:4.5rem">--:--</div></div>` : ''}
      <span class="save ${saveState}" id="save" role="status">${t(saveState === 'saved' ? 'saved' : saveState === 'pending' ? 'saving' : 'offline_syncing')}</span>
      <div class="timer" id="timer" role="timer" aria-label="${t('time_left')}">--:--</div>
      <button class="btn primary" data-act="submit">${t('submit_exam')}</button>`);
    tick();
  }

  function drawBody() {
    const secs = S.sections;
    if (S.attempt.timed_sections && !activeSection()) return drawSectionGate();
    const q = cur();
    if (!q) return mount(body, html`<div class="card empty">${t('no_questions')}</div>`);
    const sec = sectionOf(q), val = local.answers[q.id], marked = local.marked.has(q.id);
    mount(body, html`
      ${warning ? html`<div class="banner warn mt" role="alert">${warning}</div>` : ''}
      ${secs.length > 1 ? html`<div class="secbtns mt" aria-label="${t('sections')}">${secs.map((s) => html`<button class="sec-pill" data-sec="${s.id}" ${s.id === q.section_id ? 'aria-current="true"' : ''} ${S.attempt.timed_sections ? 'disabled' : ''}>${s.name}</button>`)}</div>` : ''}
      <div class="exam-layout">
        <section class="card qcard" aria-labelledby="qlabel">
          <div class="qhead"><span class="qno" id="qlabel">${t('question_n', { n: idx + 1, total: questions().length })}</span>
            <span class="chip">${q.marks} ${t('marks')}</span>${sec && secs.length > 1 ? html`<span class="chip info">${sec.name}</span>` : ''}
            <button class="btn sm right" data-act="mark" aria-pressed="${marked}">${marked ? '⚑ ' + t('unmark_review') : '⚐ ' + t('mark_review')}</button></div>
          <div class="qtext">${rich(q.text)}</div>
          ${q.type === 'fill' ? html`<div class="fill mt"><label for="fillin">${t('type_answer')}</label><input id="fillin" autocomplete="off" maxlength="500" value="${val ?? ''}"></div>`
            : html`<div class="opts" role="radiogroup" aria-labelledby="qlabel">${q.choices.map((c, n) => html`<button class="opt" role="radio" aria-checked="${val === c.i}" data-opt="${c.i}"><span class="key">${q.type === 'tf' ? (c.i === 0 ? '✓' : '✗') : LETTERS[n]}</span><span>${q.type === 'tf' ? t(c.i === 0 ? 'true' : 'false') : c.t}</span></button>`)}</div>`}
          <div class="qnav"><button class="btn" data-act="prev" ${idx === 0 ? 'disabled' : ''}>← ${t('previous')}</button><button class="btn primary" data-act="next" ${idx >= questions().length - 1 ? 'disabled' : ''}>${t('next')} →</button>
            <button class="btn" data-act="clear" ${answered(q) ? '' : 'disabled'}>${t('clear_answer')}</button>
            ${S.attempt.timed_sections ? html`<button class="btn right" data-act="finish-sec">${t('finish_section')}</button>` : ''}</div>
          <p class="tiny muted mt">${t('shortcuts_hint')}</p>
        </section>
        <aside class="card sheet" aria-label="${t('palette')}">
          <h3>${t('answer_sheet')}</h3>
          <div class="filters" role="group">${['all', 'answered', 'unanswered', 'marked'].map((f) => html`<button data-filter="${f}" aria-pressed="${filter === f}">${t('f_' + f)}</button>`)}</div>
          <div class="omr" id="omr"></div>
          <div class="legend"><span><i class="a"></i>${t('answered')}</span><span><i></i>${t('not_answered')}</span><span><i class="m"></i>${t('marked')}</span></div>
          <div class="tiny muted mt" id="counts"></div></aside>
      </div>`);
    drawSheet();
  }

  function drawSheet() {
    const omr = $('#omr', root); if (!omr) return;
    const qs = questions();
    mount(omr, html`${qs.map((q, i) => {
      const a = answered(q), m = local.marked.has(q.id);
      const show = filter === 'all' || (filter === 'answered' && a) || (filter === 'unanswered' && !a) || (filter === 'marked' && m);
      return show ? html`<button class="bub ${a ? 'ans' : ''} ${m ? 'mk' : ''} ${i === idx ? 'cur' : ''}" data-goto="${i}" aria-label="${t('question_n', { n: i + 1, total: qs.length })}${a ? ', ' + t('answered') : ''}${m ? ', ' + t('marked') : ''}" ${i === idx ? 'aria-current="true"' : ''}>${i + 1}</button>` : '';
    })}`);
    const ans = qs.filter(answered).length;
    $('#counts', root).textContent = `${t('answered')}: ${ans} · ${t('not_answered')}: ${qs.length - ans} · ${t('marked')}: ${qs.filter((q) => local.marked.has(q.id)).length}`;
  }

  function drawSectionGate() {
    const next = S.sections.find((s) => s.status === 'pending'), allDone = S.sections.every((s) => s.status === 'finished');
    mount(body, html`<div class="card mt"><h2>${t('sections')}</h2><p>${t('sections_sequential')}</p>
      <div class="col">${S.sections.map((s) => html`<div class="row between card flat"><div><b>${s.name}</b><div class="small muted">${s.count} ${t('questions')}${s.duration_min ? ' · ' + t('minutes_n', { n: s.duration_min }) : ''}</div></div>
        ${s.status === 'finished' ? html`<span class="chip ok">${t('section_done')}</span>` : s === next ? html`<button class="btn primary" data-start-sec="${s.id}">${t('start_section')}</button>` : html`<span class="chip">${t('section_locked')}</span>`}</div>`)}</div>
      ${allDone ? html`<p class="mt">${t('all_sections_done')}</p><button class="btn primary" data-act="submit">${t('submit_exam')}</button>` : ''}</div>`);
  }

  function drawOverlay() {
    const parts = [];
    if (fsLocked) parts.push(html`<div class="overlay" role="alertdialog" aria-modal="true"><div class="card"><h2>${t('fullscreen_needed')}</h2><p>${t('fullscreen_why')}</p><button class="btn primary" data-act="fs">${t('enter_fullscreen')}</button></div></div>`);
    if (camLocked) parts.push(html`<div class="overlay" role="alertdialog" aria-modal="true"><div class="card"><h2>${t('camera_needed')}</h2><p>${t('camera_why')}</p><button class="btn primary" data-act="cam">${t('try_again')}</button></div></div>`);
    mount(ov, html`${parts}`);
  }
  const redraw = () => { drawBar(); drawBody(); drawOverlay(); };

  // ------------------------------------------------------------------ timer
  function offlineExtra() {   // while offline the clock is held (up to the server's cap) because the server will credit it on reconnect
    if (!Q.offlineSince) return 0;
    const cap = Math.max(0, S.attempt.offline_credit_cap - (S.attempt.offline_credit_seconds || 0));
    return Math.min((Date.now() - Q.offlineSince) / 1000, cap) * 1000;
  }
  function tick() {
    const rem = (expiresMs + offlineExtra() - serverNow()) / 1000;
    const tm = $('#timer', root);
    if (tm) { tm.textContent = fmtClock(rem); tm.classList.toggle('low', rem < 300); tm.classList.toggle('crit', rem < 60); }
    [10, 5, 1].forEach((m) => { if (rem <= m * 60 && !warnedMin.has(m) && rem > 0) { warnedMin.add(m); live.textContent = t('minutes_left', { n: m }); } });
    const sec = activeSection(), st = $('#stimer', root);
    if (sec && st) { const srem = (Date.parse(sec.deadline || S.attempt.expires_at) + offlineExtra() - serverNow()) / 1000; st.textContent = fmtClock(srem); if (srem <= 0 && !tick.reloading) { tick.reloading = true; reloadState().finally(() => { tick.reloading = false; }); } }
    if (rem <= 0 && !done) timeUp();
  }
  let timeUpBusy = false;
  async function timeUp() {
    if (timeUpBusy) return; timeUpBusy = true;
    mount(ov, html`<div class="overlay" role="alertdialog"><div class="card"><h2>${t('time_over')}</h2><p>${t('time_over_sub')}</p></div></div>`);
    try { await flush(); await api(`/api/attempts/${attemptId}/submit`, { method: 'POST', quiet: true }); finish(); }
    catch (e) { timeUpBusy = false; if (e.status === 409 || e.status === 404) finish(); }   // offline: the sweeper submits server-side
  }

  // ------------------------------------------------------------------ saving
  function flushTime() { const q = cur(); if (!q || document.hidden) { qStart = performance.now(); return; } local.times[q.id] = (local.times[q.id] || 0) + (performance.now() - qStart) / 1000; qStart = performance.now(); }
  const timesPayload = () => { flushTime(); return Object.fromEntries(Object.entries(local.times).map(([k, v]) => [k, Math.round(v * 10) / 10])); };
  const setSave = (s) => { saveState = s; const el = $('#save', root); if (el) { el.className = `save ${s}`; el.textContent = t(s === 'saved' ? 'saved' : s === 'pending' ? 'saving' : 'offline_syncing'); } };
  function setOffline() { if (!Q.offlineSince) { Q.offlineSince = Date.now(); persist(); } setSave('offline'); }
  const isNet = (e) => e.status === 0 || e.status >= 500;

  function saveAnswer(q, extra = {}) {
    const value = local.answers[q.id] ?? null;
    pending++; setSave('pending');
    chain = chain.then(async () => {
      try {
        const body = { question_id: q.id, value, time_spent: Math.round((local.times[q.id] || 0) * 10) / 10, ...extra };
        if (Q.offlineSince || Object.keys(Q.answers).length) throw Object.assign(new Error('queued'), { status: 0 });   // keep order: send via sync
        await api(`/api/attempts/${attemptId}/answer`, { method: 'POST', body, quiet: true });
        pending--; if (!pending) setSave('saved');
      } catch (e) {
        pending--;
        if (isNet(e)) { Q.answers[q.id] = { value, ts: Date.now() }; persist(); setOffline(); }
        else if (e.status === 409 && /submitted/.test(e.message)) finish();
        else if (e.status === 401) { /* handled globally */ }
        else { toast(e.message, 'bad'); setSave('saved'); }
      }
    });
    return chain;
  }

  async function trySync() {
    if (syncing || done) return; syncing = true;
    try {
      const snaps = (await listSnapshots(attemptId)).slice(0, 8);
      const r = await api(`/api/attempts/${attemptId}/sync`, { method: 'POST', quiet: true, body: {
        answers: Object.entries(Q.answers).map(([qid, v]) => ({ question_id: +qid, value: v.value, ts: v.ts })),
        marked: [...local.marked], times: timesPayload(), events: Q.events, offline_seconds: Q.offlineSince ? (Date.now() - Q.offlineSince) / 1000 : 0,
        snapshots: snaps.map((s) => ({ image: s.image, label: s.label, ts: s.ts })) } });
      const wasOffline = !!Q.offlineSince;
      Q = { answers: {}, events: [], offlineSince: null }; persist(); await removeSnapshots(snaps.map((s) => s.id));
      applyLive(r); setSave('saved');
      if (wasOffline) toast(t('back_online'), 'ok');
      if (r.status === 'submitted' || r.auto_submitted) finish();
    } catch (e) { if (isNet(e)) setOffline(); else if (e.status === 403 && /ip_not_allowed/.test(e.message)) toast(t('ip_blocked'), 'bad'); }
    finally { syncing = false; }
  }
  const flush = async () => { await chain; if (Q.offlineSince || Object.keys(Q.answers).length || Q.events.length) await trySync(); };

  function applyLive(r) {
    if (r.expires_at) expiresMs = Date.parse(r.expires_at);
    if (r.credit_seconds) S.attempt.offline_credit_seconds = (S.attempt.offline_credit_seconds || 0) + r.credit_seconds;
    if (r.sections && S.attempt.timed_sections) S.sections.forEach((s) => { const x = r.sections[s.id]; if (x) { s.status = x.status; s.deadline = x.deadline; } });
    if (r.violations != null) S.violations = r.violations;
  }
  async function heartbeat() {
    if (done) return;
    if (Q.offlineSince || Object.keys(Q.answers).length || Q.events.length || (await listSnapshots(attemptId)).length > 0) return trySync();
    try {
      const r = await api(`/api/attempts/${attemptId}/heartbeat`, { method: 'POST', quiet: true, body: { times: timesPayload(), marked: [...local.marked] } });
      applyLive(r);
      if (r.status === 'submitted') finish();
      if (S.attempt.timed_sections && S.sections.some((s) => r.sections[s.id] && r.sections[s.id].status !== s.status)) await reloadState();
    } catch (e) { if (isNet(e)) setOffline(); }
  }
  async function reloadState() {
    const s = await api(`/api/attempts/${attemptId}/state`);
    if (s.submitted) return finish();
    const keep = cur()?.id; S = s; expiresMs = Date.parse(s.attempt.expires_at);
    idx = Math.max(0, questions().findIndex((q) => q.id === keep)); redraw();
  }

  // ------------------------------------------------------------------ proctoring events
  async function report(type, detail) {
    if (!real || done) return;
    try {
      if (Q.offlineSince) throw Object.assign(new Error('offline'), { status: 0 });
      const r = await api(`/api/attempts/${attemptId}/events`, { method: 'POST', body: { type, detail }, quiet: true });
      if (r.violations != null) S.violations = r.violations;
      if (r.auto_submitted) { toast(t('auto_submitted'), 'bad'); return finish(); }
      if (['tab_switch', 'fullscreen_exit'].includes(type) && exam.max_violations) { warning = t('warning_violation', { n: r.violations, max: exam.max_violations }); drawBody(); }
    } catch (e) { if (isNet(e)) { Q.events.push({ type, detail, ts: Date.now() / 1000 }); persist(); setOffline(); } }
  }
  async function sendSnapshot(image, label) {
    if (!real || done) return;
    try { if (Q.offlineSince) throw Object.assign(new Error('offline'), { status: 0 }); await api(`/api/attempts/${attemptId}/snapshot`, { method: 'POST', body: { image, label }, quiet: true }); }
    catch (e) { if (isNet(e)) queueSnapshot({ attemptId, image, label, ts: Date.now() / 1000 }); }
  }
  async function startProctor() {
    if (!(real && exam.camera_required)) return;
    proctor = new Proctor({ exam, report, snapshot: sendSnapshot, onStatus: (m) => { live.textContent = m; } });
    try { const host = $('#pcam', root); host.classList.remove('hidden'); await proctor.start(host); camLocked = false; }
    catch (e) { camLocked = true; report('camera_blocked', 'permission denied or no camera'); }
    drawOverlay();
  }

  // ------------------------------------------------------------------ integrity guards
  function guard(target, type, fn, opts) { target.addEventListener(type, fn, opts); offs.push(() => target.removeEventListener(type, fn, opts)); }
  if (real) {
    guard(document, 'visibilitychange', () => { if (document.hidden) report('tab_switch', 'tab hidden'); else qStart = performance.now(); });
    guard(window, 'blur', () => setTimeout(() => { if (!document.hidden && !document.hasFocus()) report('window_blur', 'window lost focus'); }, 400));
    if (exam.fullscreen_required) {
      const check = () => { if (!document.fullscreenElement && !done) { if (!fsLocked) report('fullscreen_exit', 'left full screen'); fsLocked = true; } else fsLocked = false; drawOverlay(); };
      guard(document, 'fullscreenchange', check); fsLocked = !document.fullscreenElement;
    }
    if (exam.lockdown) {
      guard(document, 'contextmenu', (e) => e.preventDefault());
      ['copy', 'cut', 'paste'].forEach((ev) => guard(document, ev, (e) => { e.preventDefault(); report('copy_paste', ev); }));
      guard(document, 'dragstart', (e) => e.preventDefault());
      guard(document, 'keydown', (e) => {
        const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey;
        const block = e.key === 'F12' || e.key === 'PrintScreen' || (mod && ['c', 'v', 'x', 'a', 'p', 's', 'u'].includes(k)) || (mod && e.shiftKey && ['i', 'j', 'c'].includes(k));
        if (block) { e.preventDefault(); report('blocked_shortcut', `${mod ? 'Ctrl+' : ''}${e.shiftKey ? 'Shift+' : ''}${e.key}`); }
      }, true);
    }
  }
  guard(window, 'beforeunload', (e) => { if (!done) { e.preventDefault(); e.returnValue = ''; } });
  guard(window, 'online', () => trySync());
  guard(window, 'offline', () => setOffline());
  guard(window, 'lang-changed', () => redraw());

  // ------------------------------------------------------------------ interaction
  function go_(i) { flushTime(); idx = Math.max(0, Math.min(questions().length - 1, i)); drawBody(); qStart = performance.now(); }
  function select(q, value) { local.answers[q.id] = value; saveAnswer(q); drawBody(); drawBar(); }
  async function submit() {
    const qs = S.exam.total_questions, ans = Object.values(local.answers).filter((v) => v !== null && v !== undefined && String(v).trim() !== '').length;
    const ok = await confirmDialog(t('confirm_submit_msg', { a: ans, n: qs, m: local.marked.size }), { okText: t('submit_exam'), title: t('confirm_submit') });
    if (!ok) return;
    try { await flush(); await api(`/api/attempts/${attemptId}/submit`, { method: 'POST' }); finish(); }
    catch (e) { toast(e.message, 'bad'); }
  }
  function finish() {
    if (done) return; done = true; localStorage.removeItem(QKEY);
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
    go(`/result/${attemptId}`);
  }

  on(root, 'click', '[data-opt]', (e, el) => { const q = cur(); select(q, +el.dataset.opt); });
  on(root, 'click', '[data-goto]', (e, el) => go_(+el.dataset.goto));
  on(root, 'click', '[data-filter]', (e, el) => { filter = el.dataset.filter; $$('[data-filter]', root).forEach((b) => b.setAttribute('aria-pressed', b.dataset.filter === filter)); drawSheet(); });
  on(root, 'click', '[data-sec]', (e, el) => { const i = questions().findIndex((q) => q.section_id === +el.dataset.sec); if (i >= 0) go_(i); });
  on(root, 'click', '[data-start-sec]', async (e, el) => { try { S = await api(`/api/attempts/${attemptId}/sections/${el.dataset.startSec}/start`, { method: 'POST' }); expiresMs = Date.parse(S.attempt.expires_at); idx = 0; redraw(); } catch (er) { toast(er.message, 'bad'); } });
  on(root, 'click', '[data-act]', async (e, el) => {
    const a = el.dataset.act, q = cur();
    if (a === 'prev') go_(idx - 1); else if (a === 'next') go_(idx + 1);
    else if (a === 'clear' && q) { local.answers[q.id] = null; saveAnswer(q); drawBody(); drawBar(); }
    else if (a === 'mark' && q) { const m = !local.marked.has(q.id); m ? local.marked.add(q.id) : local.marked.delete(q.id); saveAnswer(q, { marked: m }); drawBody(); }
    else if (a === 'submit') submit();
    else if (a === 'finish-sec') { if (await confirmDialog(t('finish_section_msg'), { okText: t('finish_section') })) { try { await flush(); S = await api(`/api/attempts/${attemptId}/sections/${activeSection().id}/finish`, { method: 'POST' }); idx = 0; redraw(); } catch (er) { toast(er.message, 'bad'); } } }
    else if (a === 'fs') { await document.documentElement.requestFullscreen?.().catch(() => {}); }
    else if (a === 'cam') startProctor();
  });
  on(root, 'input', '#fillin', (e) => { const q = cur(); local.answers[q.id] = e.target.value; const cb = $('[data-act=clear]', root); if (cb) cb.disabled = !answered(q); clearTimeout(fillTimer); fillTimer = setTimeout(() => { saveAnswer(q); drawBar(); drawSheet(); }, 600); });
  guard(document, 'keydown', (e) => {
    if (e.target.closest?.('input,textarea,[contenteditable]') || e.ctrlKey || e.metaKey || e.altKey || !cur() || ov.children.length) return;
    const q = cur(), k = e.key.toLowerCase();
    if (e.key === 'ArrowRight' || k === 'n') go_(idx + 1);
    else if (e.key === 'ArrowLeft' || k === 'p') go_(idx - 1);
    else if (k === 'm') { $('[data-act=mark]', root)?.click(); }
    else if (q.type !== 'fill') { const n = /^[1-9]$/.test(k) ? +k - 1 : LETTERS.toLowerCase().indexOf(k); if (n >= 0 && n < q.choices.length) select(q, q.choices[n].i); }
  });

  // ------------------------------------------------------------------ go
  redraw();
  startProctor();
  timers.push(setInterval(tick, 250), setInterval(heartbeat, 15000), setInterval(() => { if (!document.hidden) flushTime(); }, 5000));
  if (Q.offlineSince || Object.keys(Q.answers).length) trySync();
  return () => { done = true; timers.forEach(clearInterval); offs.forEach((f) => f()); proctor?.stop(); clearTimeout(fillTimer); document.body.classList.remove('lockdown'); };
}
