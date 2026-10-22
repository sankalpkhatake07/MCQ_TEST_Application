// Rich-text editor (bold/italic/underline, code, lists, sub/sup, images). Output is sanitised again on the server.
import { api } from './api.js';
import { html, raw, mount, sanitizeHtml, toast, esc } from './ui.js';

const BTNS = [['bold', '<b>B</b>', 'Bold'], ['italic', '<i>I</i>', 'Italic'], ['underline', '<u>U</u>', 'Underline'],
  ['code', '&lt;/&gt;', 'Inline code'], ['pre', '{ }', 'Code block'], ['ul', '• List', 'Bullet list'], ['ol', '1. List', 'Numbered list'],
  ['sub', 'x<sub>2</sub>', 'Subscript'], ['sup', 'x<sup>2</sup>', 'Superscript'], ['img', 'Image', 'Insert image'], ['clear', '⌫', 'Clear formatting']];

export function createEditor(host, { value = '', small = false, placeholder = '' } = {}) {
  mount(host, html`<div class="rte"><div class="rte-bar" role="toolbar" aria-label="Formatting">${BTNS.map(([k, label, tip]) =>
    html`<button type="button" data-cmd="${k}" title="${tip}" aria-label="${tip}">${raw(label)}</button>`)}<input type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden></div>
    <div class="rte-body ${small ? 'small' : ''}" contenteditable="true" role="textbox" aria-multiline="true" aria-label="${placeholder || 'Rich text'}" data-placeholder="${esc(placeholder)}"></div></div>`);
  const body = host.querySelector('.rte-body'), file = host.querySelector('input[type=file]');
  body.innerHTML = sanitizeHtml(value);
  const sel = () => window.getSelection().toString();
  const insert = (h) => document.execCommand('insertHTML', false, h);
  const run = (cmd) => {
    body.focus();
    if (cmd === 'bold' || cmd === 'italic' || cmd === 'underline') document.execCommand(cmd);
    else if (cmd === 'ul') document.execCommand('insertUnorderedList');
    else if (cmd === 'ol') document.execCommand('insertOrderedList');
    else if (cmd === 'sub') document.execCommand('subscript');
    else if (cmd === 'sup') document.execCommand('superscript');
    else if (cmd === 'code') insert(`<code>${esc(sel()) || 'code'}</code>&nbsp;`);
    else if (cmd === 'pre') insert(`<pre><code>${esc(sel()) || 'code'}</code></pre><p><br></p>`);
    else if (cmd === 'clear') document.execCommand('removeFormat');
    else if (cmd === 'img') file.click();
  };
  async function upload(f) {
    if (!f) return;
    const form = new FormData(); form.append('file', f, f.name);
    try { const r = await api('/api/bank/images', { method: 'POST', form }); body.focus(); insert(`<img src="${r.url}" alt="">`); }
    catch (e) { toast(e.message, 'bad'); }
  }
  host.querySelector('.rte-bar').addEventListener('mousedown', (e) => e.target.closest('[data-cmd]') && e.preventDefault());
  host.querySelector('.rte-bar').addEventListener('click', (e) => { const b = e.target.closest('[data-cmd]'); if (b) run(b.dataset.cmd); });
  file.addEventListener('change', () => { upload(file.files[0]); file.value = ''; });
  body.addEventListener('paste', (e) => {
    const items = [...(e.clipboardData?.items || [])];
    const img = items.find((i) => i.type.startsWith('image/'));
    e.preventDefault();
    if (img) return upload(img.getAsFile());
    insert(esc(e.clipboardData.getData('text/plain')).replace(/\n/g, '<br>'));   // plain text only: no pasted junk markup
  });
  return { getValue: () => sanitizeHtml(body.innerHTML).replace(/^(<p><br><\/p>)+$/, ''), focus: () => body.focus(), isEmpty: () => !body.textContent.trim() && !body.querySelector('img') };
}
