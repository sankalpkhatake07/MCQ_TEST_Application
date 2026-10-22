import { api } from '../api.js';
import { fmtNum, formModal, html, mount, on, toast } from '../ui.js';

export default async function students({ root }) {
  let list = await api('/api/students'), q = '';
  const draw = () => mount(root, html`
    <div class="row between mb"><div><h1>Students</h1><p class="muted">${list.length} registered. Students can also sign in with their email and are added automatically (if self-registration is on).</p></div>
      <div class="row"><button class="btn" data-a="tpl">Download CSV template</button><button class="btn primary" data-a="upload">Bulk upload (CSV)</button></div></div>
    <div class="card"><input id="sq" placeholder="Search name, email or roll number…" value="${q}" aria-label="Search" style="max-width:340px">
      <div class="table-wrap mt"><table><thead><tr><th>Name</th><th>Roll no</th><th>Email</th><th>Status</th></tr></thead><tbody>
      ${list.length ? list.map((s) => html`<tr><td>${s.name || '—'}</td><td>${s.roll_no || '—'}</td><td>${s.email}</td><td><span class="chip ${s.active ? 'ok' : 'bad'}">${s.active ? 'active' : 'disabled'}</span></td></tr>`) : html`<tr><td colspan="4" class="empty">No students found.</td></tr>`}</tbody></table></div></div>`);
  draw();
  let t;
  on(root, 'input', '#sq', (e) => { q = e.target.value; clearTimeout(t); t = setTimeout(async () => { list = await api(`/api/students?q=${encodeURIComponent(q)}`); draw(); const i = root.querySelector('#sq'); i.focus(); i.setSelectionRange(q.length, q.length); }, 250); });
  on(root, 'click', '[data-a=tpl]', () => {
    const url = URL.createObjectURL(new Blob(['name,email,roll_no\nAsha Patil,asha@example.com,21CS001\nRahul Deshmukh,rahul@example.com,21CS002\n'], { type: 'text/csv' }));
    Object.assign(document.createElement('a'), { href: url, download: 'students-template.csv' }).click(); setTimeout(() => URL.revokeObjectURL(url), 3000);
  });
  on(root, 'click', '[data-a=upload]', async () => {
    const r = await formModal({ title: 'Bulk upload students', submitText: 'Upload', body: html`<p class="muted small">CSV with columns <code>name, email, roll_no</code>. Existing students are updated; staff accounts are never changed.</p><label for="bf">CSV file</label><input id="bf" type="file" accept=".csv,text/csv" required>`,
      onSubmit: async (f) => { const file = f.querySelector('#bf').files[0]; if (!file) throw new Error('Choose a CSV file'); const fd = new FormData(); fd.append('file', file); return api('/api/students/bulk', { method: 'POST', form: fd }); } });
    if (!r) return;
    toast(`${r.created} added, ${r.updated} updated${r.skipped ? `, ${r.skipped} skipped` : ''}`, r.created + r.updated ? 'ok' : 'bad');
    if (r.errors?.length) await formModal({ title: 'Some rows were skipped', submitText: 'OK', body: html`<ul>${r.errors.map((x) => html`<li>${x}</li>`)}</ul>`, onSubmit: async () => true });
    list = await api('/api/students'); draw();
  });
}
