import { api } from '../api.js';
import { openQuestionEditor } from '../qeditor.js';
import { confirmDialog, formModal, fromLocalInput, html, mount, on, rich, statusChip, stripTags, toLocalInput, toast, esc } from '../ui.js';

const LANGS = { en: 'English', hi: 'हिन्दी', mr: 'मराठी' };

export default async function examEditor({ root, params, go }) {
  const id = params[0];
  let e = await api(`/api/exams/${id}`), tab = sessionStorage.getItem('ee.tab') || 'setup';
  const reload = async () => { e = await api(`/api/exams/${id}`); draw(); };
  const L = () => (e.locked ? 'disabled' : '');

  const chk = (name, label, hint, dis = '') => html`<label class="inline"><input type="checkbox" name="${name}" ${e[name] ? 'checked' : ''} ${dis}> <span>${label}${hint ? html`<br><span class="muted small">${hint}</span>` : ''}</span></label>`;
  const setup = () => html`<form id="setup" novalidate class="grid g2">
    <section class="card"><h3>Basics</h3><label for="title">Title</label><input id="title" name="title" value="${e.title}" required>
      <label for="description">Description</label><textarea id="description" name="description">${e.description || ''}</textarea>
      <label for="instructions">Instructions for students</label><textarea id="instructions" name="instructions">${e.instructions || ''}</textarea>
      <label for="duration_min">Duration (minutes)</label><input id="duration_min" name="duration_min" type="number" min="1" max="600" value="${e.duration_min}"></section>
    <section class="card"><h3>Schedule</h3>
      <label for="visible_from">Visible to students from</label><input id="visible_from" name="visible_from" type="datetime-local" value="${toLocalInput(e.visible_from)}">
      <label for="start_at">Opens (auto-open)</label><input id="start_at" name="start_at" type="datetime-local" value="${toLocalInput(e.start_at)}">
      <label for="end_at">Closes (auto-close)</label><input id="end_at" name="end_at" type="datetime-local" value="${toLocalInput(e.end_at)}">
      ${chk('strict_end', 'Hard stop at closing time', 'A student who starts late only gets the time left until the exam closes.')}
      <p class="hint">Times use your browser's time zone. Leave blank for “always open”.</p></section>
    <section class="card"><h3>Scoring</h3>
      <label for="negative_mark">Negative marking (fraction of marks lost on a wrong answer)</label>
      <select id="negative_mark" name="negative_mark" ${L()}>${[0, 0.25, 0.33, 0.5, 1].map((v) => html`<option value="${v}" ${+e.negative_mark === v ? 'selected' : ''}>${v === 0 ? 'None' : `${v} (e.g. +1 / −${v})`}</option>`)}</select>
      <label for="pass_percent">Pass mark (%)</label><input id="pass_percent" name="pass_percent" type="number" min="0" max="100" value="${e.pass_percent}">
      <h3 class="mt">Question delivery</h3>${chk('shuffle_questions', 'Shuffle question order for each student', '', L())}${chk('shuffle_options', 'Shuffle answer options for each student', '', L())}
      <h3 class="mt">After submission</h3>${chk('show_result', 'Show score immediately')}${chk('show_answers', 'Reveal correct answers and explanations')}</section>
    <section class="card"><h3>Security & proctoring</h3>
      ${chk('lockdown', 'Browser lockdown', 'Blocks copy/paste, right-click, print and developer-tool shortcuts. A deterrent, not a guarantee.')}
      ${chk('fullscreen_required', 'Require full screen')}
      <label for="max_violations">Auto-submit after this many tab-switch / full-screen violations (0 = never)</label><input id="max_violations" name="max_violations" type="number" min="0" max="100" value="${e.max_violations}">
      ${chk('camera_required', 'Webcam snapshots', 'Student must allow the camera. Snapshots are stored for your review.')}
      <label for="snapshot_interval">Snapshot every (seconds)</label><input id="snapshot_interval" name="snapshot_interval" type="number" min="10" max="600" value="${e.snapshot_interval}">
      ${chk('mic_enabled', 'Microphone activity detection')}
      ${chk('ai_proctoring', 'AI checks (in browser)', 'Face missing, several people, head turned away, different person, phone in view. Needs the camera.')}
      <label for="allowed_ips">Allowed IP addresses / CIDR ranges (one per line; blank = anywhere)</label><textarea id="allowed_ips" name="allowed_ips" placeholder="10.20.0.0/16&#10;203.0.113.7">${(e.allowed_ips || []).join('\n')}</textarea></section>
    <section class="card"><h3>Student experience</h3>
      ${chk('practice_enabled', 'Practice mode', 'After the exam closes (or after submitting) students can retake it for practice, with answers revealed.')}
      ${chk('live_ranking', 'Live ranking', 'Students see a leaderboard that updates as others submit.')}
      ${chk('certificate_enabled', 'Certificate', 'Students who reach the pass mark can download a certificate.')}
      <label>Interface languages students can choose</label>${Object.entries(LANGS).map(([k, v]) => html`<label class="inline"><input type="checkbox" name="lang_${k}" ${(e.languages || []).includes(k) ? 'checked' : ''}> ${v}</label>`)}</section>
    <div class="row" style="grid-column:1/-1"><button class="btn primary">Save settings</button>${e.locked ? html`<span class="chip warn">Scoring & shuffle rules are locked: students have started</span>` : ''}</div></form>`;

  const questionsTab = () => {
    const secs = e.sections, byId = Object.fromEntries(e.questions.map((q) => [q.id, q]));
    return html`
    ${e.locked ? html`<div class="banner warn">Students have already started this exam, so sections and questions are locked. To change them, reset the attempts from the results page or clone the exam.</div>` : ''}
    <div class="card"><div class="row between"><h3>Sections</h3><div class="row"><button class="btn sm" data-a="addsec" ${L()}>+ Section</button><button class="btn sm primary" data-a="savesec" ${L()}>Save sections</button></div></div>
      <p class="hint">Give a section a time limit and sections become sequential: students must finish each before opening the next. “Pick N” draws N random questions per student from that section’s pool.</p>
      <div class="table-wrap" style="border:0"><table><thead><tr><th>Name</th><th>Type</th><th>Time limit (min)</th><th>Pick N random</th><th></th></tr></thead><tbody id="sections">
      ${secs.map((s, i) => html`<tr data-sid="${s.id}"><td><input data-f="name" value="${s.name}" aria-label="Section name" ${L()}></td>
        <td><select data-f="qtype" ${L()}>${['mixed', 'mcq', 'tf', 'fill'].map((t) => html`<option value="${t}" ${s.qtype === t ? 'selected' : ''}>${{ mixed: 'Mixed', mcq: 'MCQ', tf: 'True/False', fill: 'Fill' }[t]}</option>`)}</select></td>
        <td><input data-f="duration_min" type="number" min="1" value="${s.duration_min ?? ''}" placeholder="none" ${L()}></td><td><input data-f="pick_count" type="number" min="1" value="${s.pick_count ?? ''}" placeholder="all" ${L()}></td>
        <td class="nowrap"><button class="btn sm icon" data-a="up" data-i="${i}" ${i === 0 || e.locked ? 'disabled' : ''} aria-label="Move up">↑</button><button class="btn sm icon" data-a="down" data-i="${i}" ${i === secs.length - 1 || e.locked ? 'disabled' : ''} aria-label="Move down">↓</button><button class="btn sm icon danger" data-a="rmsec" data-i="${i}" ${secs.length < 2 || e.locked ? 'disabled' : ''} aria-label="Remove section">✕</button></td></tr>`)}</tbody></table></div></div>
    <div class="card mt"><div class="row between"><h3>Questions (${e.questions.length})</h3><div class="row">
      <button class="btn sm" data-a="new-q" ${L()}>+ New question</button><button class="btn sm" data-a="bank" ${L()}>From bank</button><button class="btn sm" data-a="auto" ${L()}>Auto-balance</button><button class="btn sm" data-a="import" ${L()}>Import PDF / Word / CSV / JSON</button></div></div>
      ${secs.map((s) => html`<div class="section-block"><header><b>${s.name}</b><span class="chip">${s.question_ids.length} question${s.question_ids.length === 1 ? '' : 's'}</span>${s.duration_min ? html`<span class="chip info">⏱ ${s.duration_min} min</span>` : ''}${s.pick_count ? html`<span class="chip info">picks ${s.pick_count}</span>` : ''}</header>
        ${s.question_ids.length ? s.question_ids.map((qid) => { const q = byId[qid]; return html`<div class="q-list-item" style="padding:.6rem .8rem"><div class="grow"><div class="q-prev">${rich(q.text)}</div>
          <div class="row mt" style="margin-top:.3rem"><span class="chip">${q.qtype}</span><span class="chip ${{ easy: 'ok', medium: 'warn', hard: 'bad' }[q.difficulty]}">${q.difficulty}</span>${(q.tags || []).map((t) => html`<span class="chip">${t}</span>`)}</div></div>
          <input type="number" step="0.5" min="0.5" value="${q.marks}" data-marks="${q.id}" style="width:70px" aria-label="Marks" ${L()}>
          <select data-move="${q.id}" aria-label="Move to section" style="width:auto" ${L()}>${secs.map((x) => html`<option value="${x.id}" ${x.id === s.id ? 'selected' : ''}>${x.name}</option>`)}</select>
          <button class="btn sm icon danger" data-rmq="${q.id}" aria-label="Remove from exam" ${L()}>✕</button></div>`; }) : html`<div class="empty small">No questions in this section.</div>`}</div>`)}</div>`;
  };

  const shareTab = () => html`<div class="grid g2"><section class="card"><h3>Share with students</h3>
      <p>Exam ID: <code style="font-size:1.4rem">${e.id}</code></p><label>Direct link</label><input readonly value="${location.origin}/#/exam/${e.id}" onfocus="this.select()">
      <p class="hint">Students sign in, then open the link or enter the ID on “My exams”. The exam is also listed for every signed-in student once published.</p></section>
    <section class="card"><h3>Status: <span class="chip ${statusChip(e.status)}">${e.status}</span></h3><div class="col">
      <button class="btn ${e.published ? '' : 'primary'}" data-a="pub">${e.published ? 'Unpublish (hide from students)' : 'Publish exam'}</button>
      ${e.published ? html`<button class="btn" data-a="close">${e.closed_manual ? 'Re-open exam' : 'Close exam now'}</button>` : ''}
      <a class="btn" href="#/exam/${e.id}?practice=1">Preview as a student (practice attempt)</a><a class="btn" href="#/teacher/exam/${e.id}/results">View results & live monitoring</a></div></section></div>`;

  const draw = () => mount(root, html`
    <div class="row between"><div><a href="#/teacher" class="small">← All exams</a><h1>${e.title} <span class="chip ${statusChip(e.status)}">${e.status}</span></h1></div></div>
    <div class="tabs" role="tablist">${[['setup', 'Settings'], ['questions', `Questions (${e.questions.length})`], ['share', 'Publish & share']].map(([k, l]) => html`<button role="tab" aria-selected="${tab === k}" data-tab="${k}">${l}</button>`)}</div>
    ${tab === 'setup' ? setup() : tab === 'questions' ? questionsTab() : shareTab()}`);
  draw();

  const err = (m) => toast(m, 'bad');
  const sectionRows = () => [...root.querySelectorAll('#sections tr')].map((tr) => { const g = (f) => tr.querySelector(`[data-f=${f}]`).value; return { id: +tr.dataset.sid || null, name: g('name').trim() || 'Section', qtype: g('qtype'), duration_min: +g('duration_min') || null, pick_count: +g('pick_count') || null }; });
  const putSections = async (rows) => { try { e = await api(`/api/exams/${id}/sections`, { method: 'PUT', body: { sections: rows } }); draw(); } catch (x) { err(x.message); } };
  const metaOf = async () => api('/api/bank/meta');
  const secOptions = () => e.sections.map((s) => html`<option value="${s.id}">${s.name}</option>`);

  on(root, 'click', '[data-tab]', (ev, el) => { tab = el.dataset.tab; sessionStorage.setItem('ee.tab', tab); draw(); });
  on(root, 'submit', '#setup', async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target), g = (k) => f.get(k), b = (k) => ev.target.elements[k]?.checked;
    const body = { title: g('title'), description: g('description'), instructions: g('instructions'), duration_min: +g('duration_min'), visible_from: fromLocalInput(g('visible_from')), start_at: fromLocalInput(g('start_at')), end_at: fromLocalInput(g('end_at')),
      strict_end: b('strict_end'), pass_percent: +g('pass_percent'), show_result: b('show_result'), show_answers: b('show_answers'), lockdown: b('lockdown'), fullscreen_required: b('fullscreen_required'), max_violations: +g('max_violations') || 0,
      camera_required: b('camera_required'), snapshot_interval: +g('snapshot_interval') || 30, mic_enabled: b('mic_enabled'), ai_proctoring: b('ai_proctoring'), practice_enabled: b('practice_enabled'), live_ranking: b('live_ranking'), certificate_enabled: b('certificate_enabled'),
      allowed_ips: String(g('allowed_ips')).split('\n').map((x) => x.trim()).filter(Boolean), languages: Object.keys(LANGS).filter((k) => b('lang_' + k)) };
    if (!e.locked) Object.assign(body, { negative_mark: +g('negative_mark'), shuffle_questions: b('shuffle_questions'), shuffle_options: b('shuffle_options') });
    if (body.ai_proctoring && !body.camera_required) body.camera_required = true;
    try { e = await api(`/api/exams/${id}`, { method: 'PATCH', body }); toast('Settings saved', 'ok'); draw(); } catch (x) { err(x.message); }
  });
  on(root, 'click', '[data-a]', async (ev, el) => {
    const a = el.dataset.a, i = +el.dataset.i;
    if (a === 'addsec') { const rows = sectionRows(); rows.push({ id: null, name: `Section ${String.fromCharCode(65 + rows.length)}`, qtype: 'mixed', duration_min: null, pick_count: null }); putSections(rows); }
    else if (a === 'savesec') { putSections(sectionRows()); toast('Sections saved', 'ok'); }
    else if (a === 'up' || a === 'down') { const rows = sectionRows(), j = a === 'up' ? i - 1 : i + 1;[rows[i], rows[j]] = [rows[j], rows[i]]; putSections(rows); }
    else if (a === 'rmsec') { if (await confirmDialog('Its questions move to the first section.', { okText: 'Remove section', danger: true })) { const rows = sectionRows(); rows.splice(i, 1); putSections(rows); } }
    else if (a === 'new-q') {
      const q = await openQuestionEditor({ meta: await metaOf() });
      if (q?.id) { try { await api(`/api/exams/${id}/questions/add`, { method: 'POST', body: { question_ids: [q.id], section_id: e.sections[0].id } }); toast('Question added', 'ok'); reload(); } catch (x) { err(x.message); } }
    }
    else if (a === 'bank') pickFromBank();
    else if (a === 'auto') autoBalance();
    else if (a === 'import') importFile();
    else if (a === 'pub') { try { e = await api(`/api/exams/${id}/publish`, { method: 'POST', body: { published: !e.published } }); toast(e.published ? 'Published' : 'Unpublished', 'ok'); draw(); } catch (x) { err(x.message); } }
    else if (a === 'close') { try { e = await api(`/api/exams/${id}/close`, { method: 'POST', body: { closed: !e.closed_manual } }); draw(); } catch (x) { err(x.message); } }
  });
  on(root, 'change', '[data-marks]', async (ev, el) => { try { await api(`/api/exams/${id}/questions/${el.dataset.marks}`, { method: 'PATCH', body: { marks: +el.value } }); toast('Marks updated', 'ok'); } catch (x) { err(x.message); } });
  on(root, 'change', '[data-move]', async (ev, el) => { try { await api(`/api/exams/${id}/questions/${el.dataset.move}`, { method: 'PATCH', body: { section_id: +el.value } }); reload(); } catch (x) { err(x.message); } });
  on(root, 'click', '[data-rmq]', async (ev, el) => { try { await api(`/api/exams/${id}/questions/${el.dataset.rmq}`, { method: 'DELETE' }); reload(); } catch (x) { err(x.message); } });

  async function importFile() {
    const meta = await metaOf();
    const r = await formModal({ title: 'Import questions', submitText: 'Import', wide: true,
      body: html`<p class="muted small">PDF and Word: number each question (<code>Q1.</code> or <code>1)</code>), list options as <code>A)</code> <code>B)</code>…, then <code>Answer: B</code>. Optional lines: <code>Difficulty:</code> <code>Topic:</code> <code>Marks:</code> <code>Explanation:</code>. For True/False use options True/False; for fill-in-the-blank give <code>Answer: x | y</code> with no options.<br>CSV columns: <code>text, choice0…choice3, correct_index</code> (or a–d + <code>answer</code>), plus optional <code>type, difficulty, subject, tags, marks, explanation</code>.</p>
        <label for="if">File (.pdf .docx .csv .json .txt)</label><input id="if" type="file" accept=".pdf,.docx,.csv,.json,.txt" required>
        <div class="grid g3"><div><label for="isec">Add to section</label><select id="isec">${secOptions()}</select></div><div><label for="isub">Default subject</label><input id="isub" list="isubs"><datalist id="isubs">${meta.subjects.map((s) => html`<option value="${s}">`)}</datalist></div><div><label for="idf">Default difficulty</label><select id="idf"><option>medium</option><option>easy</option><option>hard</option></select></div></div>
        <label for="itg">Default tags (comma separated)</label><input id="itg">`,
      onSubmit: async (f) => { const file = f.querySelector('#if').files[0]; if (!file) throw new Error('Choose a file'); const fd = new FormData(); fd.append('file', file); fd.append('section_id', f.querySelector('#isec').value); fd.append('subject', f.querySelector('#isub').value); fd.append('difficulty', f.querySelector('#idf').value); fd.append('tags', f.querySelector('#itg').value); return api(`/api/exams/${id}/questions`, { method: 'POST', form: fd }); } });
    if (!r) return;
    toast(`Imported ${r.created} question(s)${r.skipped ? `, skipped ${r.skipped}` : ''}`, r.created ? 'ok' : 'bad');
    if (r.errors?.length) await formModal({ title: `${r.skipped} item(s) were skipped`, submitText: 'OK', body: html`<p class="muted small">These were not imported (nothing was guessed). Fix them in your file and import again.</p><ul>${r.errors.map((x) => html`<li>${x}</li>`)}</ul>`, onSubmit: async () => true });
    reload();
  }
  async function pickFromBank() {
    const meta = await metaOf(); let page = await api('/api/bank?size=100'); const chosen = new Set();
    const have = new Set(e.questions.map((q) => q.id));
    await formModal({ title: 'Add from question bank', submitText: 'Add selected', wide: true,
      body: html`<div class="row"><input id="bq" placeholder="Search text…" style="max-width:240px"><select id="bs" style="width:auto"><option value="">All subjects</option>${meta.subjects.map((s) => html`<option>${s}</option>`)}</select><select id="bd" style="width:auto"><option value="">Any difficulty</option><option>easy</option><option>medium</option><option>hard</option></select><select id="bsec" style="width:auto" aria-label="Section">${secOptions()}</select></div><div id="bl" class="mt" style="max-height:48vh;overflow:auto"></div>`,
      onReady: (f) => {
        const list = f.querySelector('#bl');
        const render = () => mount(list, html`${page.items.filter((q) => !have.has(q.id)).map((q) => html`<label class="inline q-list-item"><input type="checkbox" data-pick="${q.id}" ${chosen.has(q.id) ? 'checked' : ''}><span class="grow">${stripTags(q.text).slice(0, 140)}<br><span class="chip">${q.qtype}</span> <span class="chip">${q.difficulty}</span> ${(q.tags || []).map((t) => html`<span class="chip">${t}</span>`)}</span></label>`)}${page.items.length ? '' : html`<div class="empty">No questions match.</div>`}`);
        const refetch = async () => { const p = new URLSearchParams({ size: 100 }); [['q', '#bq'], ['subject', '#bs'], ['difficulty', '#bd']].forEach(([k, s]) => f.querySelector(s).value && p.set(k, f.querySelector(s).value)); page = await api(`/api/bank?${p}`); render(); };
        f.querySelectorAll('#bq,#bs,#bd').forEach((x) => x.addEventListener('input', refetch)); list.addEventListener('change', (ev) => { const id2 = +ev.target.dataset.pick; ev.target.checked ? chosen.add(id2) : chosen.delete(id2); }); render();
      },
      onSubmit: async (f) => { if (!chosen.size) throw new Error('Select at least one question'); const r = await api(`/api/exams/${id}/questions/add`, { method: 'POST', body: { question_ids: [...chosen], section_id: +f.querySelector('#bsec').value } }); toast(`Added ${r.added}`, 'ok'); return true; } });
    reload();
  }
  async function autoBalance() {
    const meta = await metaOf();
    const r = await formModal({ title: 'Auto-balance questions', submitText: 'Generate',
      body: html`<p class="muted small">Randomly picks questions from your bank by difficulty. Bank has ${meta.by_difficulty.easy} easy, ${meta.by_difficulty.medium} medium, ${meta.by_difficulty.hard} hard.</p>
        <div class="grid g3"><div><label for="ae">Easy</label><input id="ae" type="number" min="0" value="5"></div><div><label for="am">Medium</label><input id="am" type="number" min="0" value="3"></div><div><label for="ah">Hard</label><input id="ah" type="number" min="0" value="2"></div></div>
        <label for="asub">Subject (optional)</label><select id="asub"><option value="">Any</option>${meta.subjects.map((s) => html`<option>${s}</option>`)}</select>
        <label for="atg">Only these tags (comma separated, optional)</label><input id="atg"><label for="asec">Section</label><select id="asec">${secOptions()}</select>
        <label class="inline"><input type="checkbox" id="arep"> Replace the section's current questions</label>`,
      onSubmit: async (f) => api(`/api/exams/${id}/auto-generate`, { method: 'POST', body: { easy: +f.querySelector('#ae').value || 0, medium: +f.querySelector('#am').value || 0, hard: +f.querySelector('#ah').value || 0, subject: f.querySelector('#asub').value || null,
        tags: f.querySelector('#atg').value.split(',').map((x) => x.trim()).filter(Boolean), section_id: +f.querySelector('#asec').value, replace: f.querySelector('#arep').checked } }) });
    if (!r) return;
    const short = Object.entries(r.shortfall || {}).map(([k, v]) => `${v} ${k}`).join(', ');
    toast(`Added ${r.added} question(s)${short ? `. Not enough in the bank: ${short} short` : ''}`, short ? 'bad' : 'ok'); reload();
  }
}
