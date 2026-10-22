// Create / edit a question in the bank (MCQ, True/False, Fill in the blank) with rich text.
import { api } from './api.js';
import { createEditor } from './editor.js';
import { formModal, html, mount, on, esc } from './ui.js';

export async function openQuestionEditor({ question = null, defaults = {}, meta = { subjects: [], tags: [] } } = {}) {
  const q = question || { qtype: 'mcq', text: '', choices: ['', '', '', ''], correct: 0, difficulty: 'medium', subject: defaults.subject || '', tags: defaults.tags || [], marks: 1, explanation: '' };
  let type = q.qtype, opts = q.qtype === 'mcq' ? [...q.choices] : ['', '', '', ''], correct = q.qtype === 'fill' ? 0 : (q.correct ?? 0), accepted = Array.isArray(q.correct) ? q.correct.join('\n') : '';
  let textEd, explEd, form;

  const optsHtml = () => type === 'mcq' ? html`<label>Options <span class="hint">(select the correct one)</span></label>
      ${opts.map((o, i) => html`<div class="opt-edit"><input type="radio" name="correct" value="${i}" ${correct === i ? 'checked' : ''} aria-label="Correct option ${i + 1}"><input data-opt="${i}" value="${o}" placeholder="Option ${String.fromCharCode(65 + i)}" aria-label="Option ${i + 1}">
        <button type="button" class="btn sm icon" data-rm="${i}" aria-label="Remove option" ${opts.length <= 2 ? 'disabled' : ''}>✕</button></div>`)}
      <button type="button" class="btn sm" data-add ${opts.length >= 8 ? 'disabled' : ''}>+ Add option</button>`
    : type === 'tf' ? html`<label>Correct answer</label><label class="inline"><input type="radio" name="tf" value="0" ${correct === 0 ? 'checked' : ''}> True</label><label class="inline"><input type="radio" name="tf" value="1" ${correct === 1 ? 'checked' : ''}> False</label>`
    : html`<label for="acc">Accepted answers <span class="hint">(one per line; matching ignores case and extra spaces)</span></label><textarea id="acc">${accepted}</textarea>`;
  const drawOpts = () => mount(form.querySelector('#opts'), optsHtml());
  const syncOpts = () => { form.querySelectorAll('[data-opt]').forEach((i) => { opts[+i.dataset.opt] = i.value; }); const c = form.querySelector('input[name=correct]:checked'); if (c) correct = +c.value; const t = form.querySelector('input[name=tf]:checked'); if (t) correct = +t.value; const a = form.querySelector('#acc'); if (a) accepted = a.value; };

  return formModal({
    title: question ? 'Edit question' : 'New question', wide: true, submitText: question ? 'Save changes' : 'Create question',
    body: html`<div class="grid g3"><div><label for="qt">Type</label><select id="qt"><option value="mcq" ${type === 'mcq' ? 'selected' : ''}>Multiple choice</option><option value="tf" ${type === 'tf' ? 'selected' : ''}>True / False</option><option value="fill" ${type === 'fill' ? 'selected' : ''}>Fill in the blank</option></select></div>
      <div><label for="qd">Difficulty</label><select id="qd">${['easy', 'medium', 'hard'].map((d) => html`<option ${q.difficulty === d ? 'selected' : ''}>${d}</option>`)}</select></div>
      <div><label for="qm">Marks</label><input id="qm" type="number" step="0.5" min="0.5" value="${q.marks}"></div></div>
      <label>Question</label><div id="qtext"></div>
      <div id="opts"></div>
      <div class="grid g2"><div><label for="qs">Subject</label><input id="qs" list="subs" value="${q.subject || ''}" placeholder="e.g. Python"><datalist id="subs">${meta.subjects.map((s) => html`<option value="${s}">`)}</datalist></div>
        <div><label for="qg">Tags / topics</label><input id="qg" value="${(q.tags || []).join(', ')}" placeholder="comma separated"></div></div>
      <label>Explanation <span class="hint">(shown after the exam if answers are revealed)</span></label><div id="qexp"></div>`,
    onReady: (f) => {
      form = f;
      textEd = createEditor(f.querySelector('#qtext'), { value: q.text, placeholder: 'Question text' });
      explEd = createEditor(f.querySelector('#qexp'), { value: q.explanation || '', small: true, placeholder: 'Explanation' });
      drawOpts();
      f.querySelector('#qt').onchange = (e) => { syncOpts(); type = e.target.value; if (type === 'tf') correct = 0; if (type === 'mcq') correct = Math.min(correct, opts.length - 1); drawOpts(); };
      on(f, 'click', '[data-add]', () => { syncOpts(); opts.push(''); drawOpts(); });
      on(f, 'click', '[data-rm]', (e, el) => { syncOpts(); const i = +el.dataset.rm; opts.splice(i, 1); if (correct >= opts.length) correct = 0; else if (correct > i) correct--; drawOpts(); });
    },
    onSubmit: async () => {
      syncOpts();
      if (textEd.isEmpty()) throw new Error('Enter the question text');
      const body = { text: textEd.getValue(), qtype: type, difficulty: form.querySelector('#qd').value, marks: +form.querySelector('#qm').value || 1,
        subject: form.querySelector('#qs').value.trim() || null, tags: form.querySelector('#qg').value.split(',').map((x) => x.trim()).filter(Boolean),
        explanation: explEd.isEmpty() ? null : explEd.getValue(), choices: [], correct: null };
      if (type === 'mcq') { body.choices = opts.map((o) => o.trim()).filter(Boolean); if (opts[correct] !== undefined && !opts[correct].trim()) throw new Error('The correct option is empty'); body.correct = opts.slice(0, correct).filter((o) => o.trim()).length; }
      else if (type === 'tf') body.correct = correct;
      else body.correct = accepted.split('\n').map((x) => x.trim()).filter(Boolean);
      return question ? api(`/api/bank/${question.id}`, { method: 'PUT', body }) : api('/api/bank', { method: 'POST', body });
    },
  });
}
