import { api } from '../api.js';
import { openQuestionEditor } from '../qeditor.js';
import { confirmDialog, formModal, html, mount, on, rich, stripTags, toast } from '../ui.js';

export default async function bank({ root }) {
  let meta = await api('/api/bank/meta'), data = { items: [], total: 0 }, f = { q: '', subject: '', tag: '', difficulty: '', qtype: '' }, page = 1;
  const SIZE = 20;
  const load = async () => { const p = new URLSearchParams({ page, size: SIZE }); Object.entries(f).forEach(([k, v]) => v && p.set(k, v)); [meta, data] = await Promise.all([api('/api/bank/meta'), api(`/api/bank?${p}`)]); draw(); };
  const draw = () => mount(root, html`
    <div class="row between mb"><div><h1>Question bank</h1><p class="muted">${meta.total} questions · ${meta.by_difficulty.easy} easy · ${meta.by_difficulty.medium} medium · ${meta.by_difficulty.hard} hard</p></div>
      <div class="row"><button class="btn" data-a="import">Import file</button><button class="btn primary" data-a="new">+ New question</button></div></div>
    <div class="card"><div class="row"><input id="fq" placeholder="Search text…" value="${f.q}" style="max-width:240px" aria-label="Search">
      <select id="fs" aria-label="Subject" style="width:auto"><option value="">All subjects</option>${meta.subjects.map((s) => html`<option ${f.subject === s ? 'selected' : ''}>${s}</option>`)}</select>
      <select id="ft" aria-label="Tag" style="width:auto"><option value="">All tags</option>${meta.tags.map((s) => html`<option ${f.tag === s ? 'selected' : ''}>${s}</option>`)}</select>
      <select id="fd" aria-label="Difficulty" style="width:auto"><option value="">Any difficulty</option>${['easy', 'medium', 'hard'].map((s) => html`<option ${f.difficulty === s ? 'selected' : ''}>${s}</option>`)}</select>
      <select id="fy" aria-label="Type" style="width:auto"><option value="">Any type</option>${[['mcq', 'MCQ'], ['tf', 'True/False'], ['fill', 'Fill']].map(([k, l]) => html`<option value="${k}" ${f.qtype === k ? 'selected' : ''}>${l}</option>`)}</select></div>
      ${data.items.length ? html`<div class="mt">${data.items.map((q) => html`<div class="q-list-item"><div class="grow"><div class="q-prev">${rich(q.text)}</div>
        <div class="row" style="margin-top:.3rem"><span class="chip">${q.qtype}</span><span class="chip ${{ easy: 'ok', medium: 'warn', hard: 'bad' }[q.difficulty]}">${q.difficulty}</span>${q.subject ? html`<span class="chip info">${q.subject}</span>` : ''}${(q.tags || []).map((t) => html`<span class="chip">${t}</span>`)}<span class="tiny muted">${q.marks} mark${q.marks === 1 ? '' : 's'}</span></div></div>
        <button class="btn sm" data-edit="${q.id}">Edit</button><button class="btn sm danger" data-del="${q.id}" aria-label="Delete question">Delete</button></div>`)}</div>
        <div class="row between mt"><span class="small muted">${data.total} match${data.total === 1 ? '' : 'es'}</span><div class="row"><button class="btn sm" data-pg="-1" ${page <= 1 ? 'disabled' : ''}>← Prev</button><span class="small">Page ${page} of ${Math.max(1, Math.ceil(data.total / SIZE))}</span><button class="btn sm" data-pg="1" ${page * SIZE >= data.total ? 'disabled' : ''}>Next →</button></div></div>`
        : html`<div class="empty">${meta.total ? 'No questions match these filters.' : 'Your bank is empty. Create a question or import a PDF / Word / CSV file.'}</div>`}</div>`);
  let timer;
  on(root, 'input', '#fq', (e) => { f.q = e.target.value; page = 1; clearTimeout(timer); timer = setTimeout(async () => { await load(); root.querySelector('#fq').focus(); const i = root.querySelector('#fq'); i.setSelectionRange(i.value.length, i.value.length); }, 300); });
  for (const [sel, key] of [['#fs', 'subject'], ['#ft', 'tag'], ['#fd', 'difficulty'], ['#fy', 'qtype']]) on(root, 'change', sel, (e) => { f[key] = e.target.value; page = 1; load(); });
  on(root, 'click', '[data-pg]', (e, el) => { page += +el.dataset.pg; load(); });
  on(root, 'click', '[data-a=new]', async () => { if (await openQuestionEditor({ meta })) { toast('Question created', 'ok'); load(); } });
  on(root, 'click', '[data-edit]', async (e, el) => { const q = data.items.find((x) => x.id === +el.dataset.edit); if (await openQuestionEditor({ question: q, meta })) { toast('Question updated', 'ok'); load(); } });
  on(root, 'click', '[data-del]', async (e, el) => { if (await confirmDialog('Remove this question from your bank and from any exams that use it?', { okText: 'Delete', danger: true })) { try { await api(`/api/bank/${el.dataset.del}`, { method: 'DELETE' }); toast('Deleted', 'ok'); load(); } catch (er) { toast(er.message, 'bad'); } } });
  on(root, 'click', '[data-a=import]', async () => {
    const r = await formModal({ title: 'Import into question bank', submitText: 'Import', wide: true,
      body: html`<p class="muted small">PDF / Word: <code>Q1. text</code>, options <code>A) …</code>, then <code>Answer: B</code> (optional <code>Difficulty:</code> <code>Topic:</code> <code>Marks:</code> <code>Explanation:</code>). CSV: <code>text, choice0…, correct_index</code> + optional <code>type, difficulty, subject, tags, marks, explanation</code>. JSON: list of objects with the same fields.</p>
        <label for="if">File</label><input id="if" type="file" accept=".pdf,.docx,.csv,.json,.txt" required>
        <div class="grid g3"><div><label for="isub">Default subject</label><input id="isub"></div><div><label for="idf">Default difficulty</label><select id="idf"><option>medium</option><option>easy</option><option>hard</option></select></div><div><label for="itg">Default tags</label><input id="itg" placeholder="comma separated"></div></div>`,
      onSubmit: async (fm) => { const file = fm.querySelector('#if').files[0]; if (!file) throw new Error('Choose a file'); const fd = new FormData(); fd.append('file', file); fd.append('subject', fm.querySelector('#isub').value); fd.append('difficulty', fm.querySelector('#idf').value); fd.append('tags', fm.querySelector('#itg').value); return api('/api/bank/import', { method: 'POST', form: fd }); } });
    if (!r) return;
    toast(`Imported ${r.created} question(s)${r.skipped ? `, skipped ${r.skipped}` : ''}`, r.created ? 'ok' : 'bad');
    if (r.errors?.length) await formModal({ title: `${r.skipped} item(s) were skipped`, submitText: 'OK', body: html`<p class="muted small">Nothing was guessed: fix these in your file and import again.</p><ul>${r.errors.map((x) => html`<li>${x}</li>`)}</ul>`, onSubmit: async () => true });
    load();
  });
  await load();
}
