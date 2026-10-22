import { api, auth } from '../api.js';
import { confirmDialog, fmtDate, formModal, html, mount, on, statusChip, toast } from '../ui.js';

export default async function admin({ root }) {
  let tab = 'users', users = [], exams = [], stats = null, q = '', role = '';
  const me = auth.user;
  const load = async () => {
    if (tab === 'users') users = await api(`/api/admin/users?q=${encodeURIComponent(q)}${role ? `&role=${role}` : ''}`);
    else if (tab === 'exams') exams = await api('/api/admin/exams');
    else stats = await api('/api/admin/stats');
    draw();
  };
  const usersTab = () => html`<div class="row between mb"><div class="row"><input id="uq" placeholder="Search…" value="${q}" style="max-width:240px" aria-label="Search users"><select id="ur" style="width:auto" aria-label="Role"><option value="">All roles</option>${['student', 'teacher', 'admin'].map((r) => html`<option ${role === r ? 'selected' : ''}>${r}</option>`)}</select></div><button class="btn primary" data-a="add">+ Add user</button></div>
    <div class="table-wrap"><table><thead><tr><th>User</th><th>Role</th><th>MFA</th><th>Status</th><th>Last login</th><th></th></tr></thead><tbody>
    ${users.map((u) => html`<tr><td><b>${u.name || '—'}</b><div class="tiny muted">${u.email}${u.roll_no ? ' · ' + u.roll_no : ''}</div></td>
      <td><select data-role="${u.id}" aria-label="Role for ${u.email}" style="width:auto" ${u.id === me.id ? 'disabled' : ''}>${['student', 'teacher', 'admin'].map((r) => html`<option ${u.role === r ? 'selected' : ''}>${r}</option>`)}</select></td>
      <td><input type="checkbox" data-mfa="${u.id}" ${u.mfa_enabled ? 'checked' : ''} aria-label="MFA for ${u.email}" ${u.has_password ? '' : 'disabled title="Set a password first"'}></td>
      <td><label class="inline" style="margin:0"><input type="checkbox" data-active="${u.id}" ${u.active ? 'checked' : ''} ${u.id === me.id ? 'disabled' : ''}> ${u.active ? 'active' : 'disabled'}</label></td><td class="small">${fmtDate(u.last_login)}</td>
      <td class="nowrap"><button class="btn sm" data-pw="${u.id}" data-email="${u.email}">Set password</button> <button class="btn sm danger" data-del="${u.id}" data-email="${u.email}" ${u.id === me.id ? 'disabled' : ''}>Delete</button></td></tr>`)}</tbody></table></div>`;
  const examsTab = () => html`<div class="table-wrap"><table><thead><tr><th>ID</th><th>Title</th><th>Owner</th><th>Status</th><th>Attempts</th><th></th></tr></thead><tbody>${exams.map((e) => html`<tr><td>${e.id}</td><td>${e.title}</td><td>${e.owner || '—'}</td><td><span class="chip ${statusChip(e.status)}">${e.status}</span></td><td>${e.attempt_count}</td>
    <td class="nowrap"><a class="btn sm" href="#/teacher/exam/${e.id}">Open</a> <a class="btn sm" href="#/teacher/exam/${e.id}/results">Results</a> <button class="btn sm danger" data-delexam="${e.id}">Delete</button></td></tr>`)}</tbody></table></div>`;
  const sysTab = () => html`<div class="grid g4 mb">${[['Users', stats.users], ['Students', stats.students], ['Teachers', stats.teachers], ['Admins', stats.admins], ['Exams', stats.exams], ['Questions', stats.questions], ['Attempts', stats.attempts]].map(([l, v]) => html`<div class="stat"><b>${v}</b><span>${l}</span></div>`)}</div>
    <div class="card"><h3>Infrastructure</h3><dl class="kv"><dt>Database</dt><dd>${stats.database}</dd><dt>File storage</dt><dd>${stats.storage_backend}</dd><dt>Redis (live events across servers)</dt><dd>${stats.redis ? 'connected' : 'not configured (single server mode)'}</dd><dt>MongoDB event mirror</dt><dd>${stats.mongo_mirror ? 'enabled' : 'off'}</dd></dl></div>`;
  const draw = () => mount(root, html`<h1>Administration</h1><div class="tabs" role="tablist">${[['users', 'Users & roles'], ['exams', 'All exams'], ['system', 'System']].map(([k, l]) => html`<button role="tab" aria-selected="${tab === k}" data-tab="${k}">${l}</button>`)}</div>${tab === 'users' ? usersTab() : tab === 'exams' ? examsTab() : sysTab()}`);
  const patch = async (id, body, msg = 'Saved') => { try { await api(`/api/admin/users/${id}`, { method: 'PATCH', body }); toast(msg, 'ok'); } catch (e) { toast(e.message, 'bad'); } await load(); };
  on(root, 'click', '[data-tab]', (e, el) => { tab = el.dataset.tab; load(); });
  let t; on(root, 'input', '#uq', (e) => { q = e.target.value; clearTimeout(t); t = setTimeout(async () => { await load(); const i = root.querySelector('#uq'); i.focus(); i.setSelectionRange(q.length, q.length); }, 250); });
  on(root, 'change', '#ur', (e) => { role = e.target.value; load(); });
  on(root, 'change', '[data-role]', (e, el) => patch(el.dataset.role, { role: el.value }, 'Role updated. They were signed out.'));
  on(root, 'change', '[data-active]', (e, el) => patch(el.dataset.active, { active: el.checked }));
  on(root, 'change', '[data-mfa]', (e, el) => patch(el.dataset.mfa, { mfa_enabled: el.checked }));
  on(root, 'click', '[data-a=add]', async () => {
    const r = await formModal({ title: 'Add user', submitText: 'Create user', body: html`<div class="grid g2"><div><label for="an">Name</label><input id="an"></div><div><label for="ae">Email</label><input id="ae" type="email" required></div><div><label for="ar">Role</label><select id="ar"><option>student</option><option>teacher</option><option>admin</option></select></div><div><label for="arn">Roll no (students)</label><input id="arn"></div></div>
      <label for="ap">Password (optional; they can also sign in with an emailed code)</label><input id="ap" type="password" autocomplete="new-password"><p class="hint">At least 8 characters with an uppercase letter and a digit.</p>`,
      onSubmit: async (f) => api('/api/admin/users', { method: 'POST', body: { name: f.querySelector('#an').value || null, email: f.querySelector('#ae').value.trim(), role: f.querySelector('#ar').value, roll_no: f.querySelector('#arn').value || null, password: f.querySelector('#ap').value || null } }) });
    if (r) { toast('User created', 'ok'); load(); }
  });
  on(root, 'click', '[data-pw]', async (e, el) => {
    const r = await formModal({ title: `Set password for ${el.dataset.email}`, submitText: 'Set password', body: html`<label for="sp">New password</label><input id="sp" type="password" autocomplete="new-password" autofocus><p class="hint">At least 8 characters with an uppercase letter and a digit.</p>`,
      onSubmit: async (f) => api(`/api/admin/users/${el.dataset.pw}`, { method: 'PATCH', body: { password: f.querySelector('#sp').value } }) });
    if (r) { toast('Password set', 'ok'); load(); }
  });
  on(root, 'click', '[data-del]', async (e, el) => { if (await confirmDialog(`Delete ${el.dataset.email}? Accounts with exams or attempts cannot be deleted: disable them instead.`, { okText: 'Delete user', danger: true })) { try { await api(`/api/admin/users/${el.dataset.del}`, { method: 'DELETE' }); toast('Deleted', 'ok'); load(); } catch (er) { toast(er.message, 'bad'); } } });
  on(root, 'click', '[data-delexam]', async (e, el) => { if (await confirmDialog('Delete this exam with all attempts and snapshots?', { okText: 'Delete exam', danger: true })) { try { await api(`/api/exams/${el.dataset.delexam}`, { method: 'DELETE' }); toast('Deleted', 'ok'); load(); } catch (er) { toast(er.message, 'bad'); } } });
  await load();
}
