// Minimal IndexedDB queue used for offline proctoring snapshots (too big for localStorage).
const DB = 'examhub', STORE = 'snapshots';
const open = () => new Promise((res, rej) => {
  const r = indexedDB.open(DB, 1);
  r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
  r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
});
const tx = async (mode, fn) => { const db = await open(); return new Promise((res, rej) => { const t = db.transaction(STORE, mode); const out = fn(t.objectStore(STORE)); t.oncomplete = () => res(out.result); t.onerror = () => rej(t.error); }); };
export const queueSnapshot = (item) => tx('readwrite', (s) => s.add(item)).catch(() => {});
export const listSnapshots = (attemptId) => tx('readonly', (s) => s.getAll()).then((all) => all.filter((x) => x.attemptId === attemptId)).catch(() => []);
export const removeSnapshots = (ids) => tx('readwrite', (s) => { ids.forEach((i) => s.delete(i)); return { result: true }; }).catch(() => {});
