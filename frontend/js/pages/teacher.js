import { api } from '../api.js';
import { confirmDialog, fmtDate, formModal, html, mount, on, statusChip, toast } from '../ui.js';

export default async function teacher({ root, go, user }) {
  let exams = [];
  const load = async () => { exams = await api('/api/exams'); draw(); };
  const draw = () => mount(root, html`
    <div class="row between mb"><div><h1>Exams</h1><p class="muted">${user.role === 'admin' ? 'All exams in the system.' : 'Your exams.'} Students join with the exam ID.</p></div><button class="btn primary" data-a="new">+ New exam</button></div>
    ${exams.length ? html`<div class="card" style="padding:0"><div class="table-wrap" style="border:0"><table><thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Window</th><th>Questions</th><th>Attempts</th><th></th></tr></thead><tbody>
      ${exams.map((e) => html`<tr><td><code>${e.id}</code></td><td><a href="#/teacher/exam/${e.id}"><b>${e.title}</b></a><div class="tiny muted">${e.duration_min} min${e.negative_mark ? ` · −${e.negative_mark}` : ''}</div></td>
        <td><span class="chip ${statusChip(e.status)}">${e.status}</span></td><td class="small">${e.start_at ? fmtDate(e.start_at) : 'Anytime'}${e.end_at ? html`<br>→ ${fmtDate(e.end_at)}` : ''}</td>
        <td>${e.question_count}</td><td>${e.submitted_count}/${e.attempt_count}</td>
        <td class="nowrap"><a class="btn sm" href="#/teacher/exam/${e.id}">Edit</a> <a class="btn sm" href="#/teacher/exam/${e.id}/results">Results</a>
          <button class="btn sm" data-a="pub" data-id="${e.id}" data-v="${!e.published}">${e.published ? 'Unpublish' : 'Publish'}</button>
          <button class="btn sm danger" data-a="del" data-id="${e.id}" aria-label="Delete ${e.title}">Delete</button></td></tr>`)}</tbody></table></div></div>`
      : html`<div class="card empty"><h3>No exams yet</h3><p>Create an exam, add questions from your bank (or import a PDF / Word / CSV file), then publish it.</p><button class="btn primary" data-a="new">+ New exam</button></div>`}`);
  on(root, 'click', '[data-a]', async (e, el) => {
    const a = el.dataset.a, id = el.dataset.id;
    if (a === 'new') {
      const e2 = await formModal({ title: 'New exam', submitText: 'Create exam', body: html`<label for="n-t">Title</label><input id="n-t" required autofocus placeholder="e.g. Python Basics - Unit 1"><label for="n-d">Duration (minutes)</label><input id="n-d" type="number" min="1" max="600" value="30">`,
        onSubmit: async (f) => { const title = f.querySelector('#n-t').value.trim(); if (!title) throw new Error('Enter a title'); return api('/api/exams', { method: 'POST', body: { title, duration_min: +f.querySelector('#n-d').value || 30 } }); } });
      if (e2?.id) go(`/teacher/exam/${e2.id}`);
    } else if (a === 'pub') {
      try { await api(`/api/exams/${id}/publish`, { method: 'POST', body: { published: el.dataset.v === 'true' } }); toast(el.dataset.v === 'true' ? 'Published' : 'Unpublished', 'ok'); load(); } catch (er) { toast(er.message, 'bad'); }
    } else if (a === 'del') {
      if (await confirmDialog('This permanently deletes the exam, all attempts, results and proctoring snapshots.', { okText: 'Delete exam', danger: true, title: 'Delete exam?' })) {
        try { await api(`/api/exams/${id}`, { method: 'DELETE' }); toast('Deleted', 'ok'); load(); } catch (er) { toast(er.message, 'bad'); }
      }
    }
  });
  await load();
}
