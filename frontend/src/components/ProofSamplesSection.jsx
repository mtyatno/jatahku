import { useState, useEffect, useCallback, useRef, useId } from 'react';
import { api } from '../lib/api';
import { native } from '../native';
import {
  SAMPLE_TABS, PSEUDONYM_CHOICES, EXPECT_LABEL, READING_LABEL, TRUTH_LABEL, STEP_PARTS, sampleCounts, sampleRows,
  editableLines, linesNotice, approveBody, rejectBody, entryDownload, actionOutcome, confirmText, nextSampleTab, emptyText,
} from '../lib/proofSamples';

// Bagian "Donasi contoh" kartu Admin Scan Struk (tahap 2 M1e). Semua logika (tab, baris, PERIKSA, perbandingan hasil
// baca vs koreksi user, body Setujui/Tolak, berkas unduhan, pesan galat) ada di lib/proofSamples.js; komponen ini hanya
// memuat data, menyimpan state, dan merender. Warna mengikuti ProofRulesSection (≥ 4,5:1 di semua tema).
// Aksesibilitas: pola tab WAI-ARIA, wilayah live status/alert yang selalu ada, tombol memakai aria-disabled.
const MESSAGE_CLASS = { ok: 'text-green-700', conflict: 'text-amber-600', invalid: 'text-amber-600', error: 'text-amber-600' };
const PSEUDONYM_VALUES = new Set(PSEUDONYM_CHOICES.map(c => c.value));

export default function ProofSamplesSection() {
  const uid = useId();
  const tabId = key => `${uid}-tab-${key}`;
  const panelId = `${uid}-panel`;
  const [tab, setTab] = useState('menunggu');
  const [resp, setResp] = useState(undefined);   // undefined = memuat, null = gagal
  const [busy, setBusy] = useState(false);
  const [drafts, setDrafts] = useState({});
  const [entries, setEntries] = useState({});
  const [message, setMessage] = useState(null);
  const alive = useRef(true);
  const tabRefs = useRef({});
  useEffect(() => () => { alive.current = false; }, []);

  const load = useCallback(async () => {
    const data = await api.adminProofSamples('semua');
    if (alive.current) setResp(data);
  }, []);
  useEffect(() => { load(); }, [load]);

  function selectTab(key) {
    setTab(key);
    setMessage(null);
  }

  function onTabKey(e) {
    const key = nextSampleTab(tab, e.key);
    if (!key) return;
    e.preventDefault();
    selectTab(key);
    tabRefs.current[key]?.focus();
  }

  const draftOf = row => drafts[row.id] || {
    lines: editableLines(row) ?? '',
    userName: PSEUDONYM_VALUES.has(row.userName ?? '') ? (row.userName ?? '') : '',
    note: '',
  };
  const setDraft = (row, patch) => setDrafts(d => ({ ...d, [row.id]: { ...draftOf(row), ...patch } }));

  async function run(action, row, call) {
    if (busy) return;
    const ask = confirmText(action);
    if (ask && !window.confirm(ask)) return;
    setBusy(true);
    setMessage(null);
    const out = actionOutcome(action, await call());
    if (!alive.current) return;
    if (out.kind === 'ok') {
      setDrafts(({ [row.id]: _d, ...rest }) => rest);
      setEntries(({ [row.id]: _e, ...rest }) => rest);
    }
    if (out.reload) await load();
    if (!alive.current) return;
    setMessage(out);
    setBusy(false);
  }

  function approve(row) {
    const d = draftOf(row);
    const body = approveBody(row, d.lines, d.userName, d.note);
    if (!body) return;
    run('setujui', row, () => api.adminProofSampleAction(row.id, 'setujui', body));
  }

  function reject(row) {
    const body = rejectBody(row, draftOf(row).note);
    if (!body) return;
    run('tolak', row, () => api.adminProofSampleAction(row.id, 'tolak', body));
  }

  async function download(row) {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    const res = await api.adminProofSampleEntry(row.id);
    if (!alive.current) return;
    const file = res.ok ? entryDownload(res.data) : null;
    if (file) {
      setEntries(e => ({ ...e, [row.id]: file }));
      try {
        await native.files.save(new Blob([file.text], { type: 'application/json' }), file.fileName);
        if (alive.current) setMessage({ kind: 'ok', text: `Berkas ${file.fileName} disimpan.` });
      } catch {
        if (alive.current) setMessage({ kind: 'error', text: 'Berkas tidak bisa disimpan. Coba lagi.' });
      }
    } else {
      const out = res.ok ? { kind: 'error', text: 'Entri korpus tidak terbaca. Coba lagi.', reload: false } : actionOutcome('unduh', res);
      if (out.reload) await load();
      if (alive.current) setMessage(out);
    }
    if (alive.current) setBusy(false);
  }

  const counts = sampleCounts(resp);
  const rows = sampleRows(resp, tab);
  const polite = message && message.kind === 'ok' ? message : null;
  const urgent = message && message.kind !== 'ok' ? message : null;

  return (
    <div className="mt-4 pt-3 border-t border-gray-100">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h4 className="text-sm font-semibold text-gray-800">Donasi contoh</h4>
        {resp && <p className="text-xs text-gray-500">{counts.menunggu} menunggu · {counts.disetujui} disetujui</p>}
      </div>
      <div role="tablist" aria-label="Donasi contoh" className="mt-2 flex flex-wrap gap-1">
        {SAMPLE_TABS.map(t => (
          <button key={t.key} type="button" role="tab" id={tabId(t.key)} aria-selected={tab === t.key}
            aria-controls={panelId} tabIndex={tab === t.key ? 0 : -1}
            ref={(el) => { tabRefs.current[t.key] = el; }}
            onClick={() => selectTab(t.key)} onKeyDown={onTabKey}
            className={`px-2.5 py-1 rounded-lg text-xs font-medium ${tab === t.key ? 'bg-brand-50 text-gray-800 font-semibold' : 'text-gray-500 hover:bg-gray-50'}`}>
            {t.label}
          </button>
        ))}
      </div>

      <p role="status" aria-live="polite" className={`text-xs ${polite ? MESSAGE_CLASS[polite.kind] : ''}`}>
        {polite && <span className="block mt-2">{polite.text}</span>}
      </p>
      <p role="alert" className="text-xs text-amber-600">
        {urgent && <span className="block mt-2">{urgent.text}</span>}
      </p>

      <div role="tabpanel" id={panelId} aria-labelledby={tabId(tab)} tabIndex={0} className="mt-2">
        {resp === undefined && <p className="text-xs text-gray-500">Memuat…</p>}
        {resp !== undefined && !rows && (
          <p className="text-xs text-amber-600">
            Daftar sampel tidak bisa dimuat.{' '}
            <button type="button" className="underline" onClick={() => { setResp(undefined); load(); }}>Muat ulang</button>
          </p>
        )}
        {rows?.length === 0 && <p className="text-xs text-gray-500">{emptyText(tab)}</p>}
        {rows?.length > 0 && (
          <ul>
            {rows.map((r) => {
              const d = draftOf(r);
              const notice = r.status === 'menunggu' ? linesNotice(d.lines) : null;
              const canApprove = !busy && approveBody(r, d.lines, d.userName, d.note) !== null;
              const file = entries[r.id];
              const linesId = `${uid}-${r.id}-lines`;
              const periksaId = `${uid}-${r.id}-periksa`;
              return (
                <li key={r.id} className="py-2 border-t border-gray-100 text-xs">
                  <h5 className="flex flex-wrap items-baseline gap-x-2 font-normal">
                    <span className="font-semibold text-gray-800">{r.app}</span>
                    <span className="text-gray-500">{r.trigger}</span>
                  </h5>
                  {r.date && <div className="text-gray-500">{r.date}</div>}
                  {r.note && <div className="text-gray-500 break-words">Catatan: {r.note}</div>}

                  {r.status === 'menunggu' && (
                    <table className="mt-1 w-full text-xs">
                      <thead>
                        <tr className="text-gray-500">
                          <th scope="col" className="text-left font-medium py-0.5"><span className="sr-only">Field</span></th>
                          <th scope="col" className="text-left font-medium py-0.5">{READING_LABEL}</th>
                          <th scope="col" className="text-left font-medium py-0.5">{TRUTH_LABEL}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {r.compare.map(c => (
                          <tr key={c.field} className={c.differs ? 'text-amber-600' : 'text-gray-700'}>
                            <th scope="row" className="text-left font-normal text-gray-500 pr-2">{c.label}</th>
                            <td className="pr-2">{c.read}</td>
                            <td>{c.fixed}{c.differs && <span className="sr-only"> (berbeda)</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {r.status === 'menunggu' && r.readingMissing && (
                    <p className="text-gray-500">Pembaca belum bisa membaca baris ini.</p>
                  )}

                  {r.periksa > 0 && (
                    <div id={periksaId} className="mt-1">
                      <p className="text-amber-600">⚠ {r.periksaText} — cek nomor atau nama yang tersisa.</p>
                      <ul className="font-mono text-gray-700">
                        {r.lines.filter(l => l.periksa).map(l => (
                          <li key={l.n} className="break-words"><span className="text-amber-600">PERIKSA {l.n}:</span> {l.text}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {r.status === 'menunggu' ? (
                    <div className="mt-2 space-y-2">
                      <label htmlFor={linesId} className="block text-gray-500">Baris sampel (satu baris per baris bukti; ganti nama yang tersisa)</label>
                      <textarea id={linesId} rows={Math.min(Math.max(r.lines.length, 4), 14)}
                        className="input w-full font-mono text-xs py-1.5 px-3"
                        aria-describedby={r.periksa > 0 ? periksaId : undefined}
                        value={d.lines} disabled={busy} spellCheck={false}
                        onChange={e => setDraft(r, { lines: e.target.value })} />
                      {notice && <p className="text-amber-600">{notice}</p>}
                      <div className="flex flex-wrap items-center gap-2">
                        <label className="flex items-center gap-2 text-gray-500">
                          Nama samaran user
                          <select className="input py-1.5 px-2 text-xs" value={d.userName} disabled={busy}
                            onChange={e => setDraft(r, { userName: e.target.value })}>
                            {PSEUDONYM_CHOICES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                          </select>
                        </label>
                        <input type="text" className="input py-1.5 px-3 text-xs flex-1 min-w-[10rem] placeholder:text-gray-500"
                          placeholder="Catatan (opsional, maks. 200)" aria-label={`Catatan untuk sampel ${r.app}`}
                          value={d.note} disabled={busy} onChange={e => setDraft(r, { note: e.target.value })} />
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button type="button" aria-disabled={!canApprove} onClick={() => canApprove && approve(r)}
                          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-green-50 text-green-700 hover:bg-green-100 aria-disabled:opacity-50 aria-disabled:cursor-not-allowed">
                          Setujui
                        </button>
                        <button type="button" aria-disabled={busy} onClick={() => reject(r)}
                          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 text-gray-700 hover:bg-gray-50 aria-disabled:opacity-50 aria-disabled:cursor-not-allowed">
                          Tolak
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-2 space-y-2">
                      <pre className="font-mono text-gray-700 whitespace-pre-wrap break-words">{editableLines(r)}</pre>
                      {file && (
                        <div>
                          <p className="text-gray-500">{EXPECT_LABEL}:</p>
                          <ul className="text-gray-700">
                            {file.expect.map(e => <li key={e.field}>{e.label}: {e.value}</li>)}
                          </ul>
                          {file.diffText && <p className="text-amber-600">{file.diffText}</p>}
                        </div>
                      )}
                      <div className="flex flex-wrap gap-2">
                        <button type="button" aria-disabled={busy} onClick={() => download(r)}
                          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-green-50 text-green-700 hover:bg-green-100 aria-disabled:opacity-50 aria-disabled:cursor-not-allowed">
                          Unduh entri korpus
                        </button>
                        <button type="button" aria-disabled={busy}
                          onClick={() => run('hapus', r, () => api.adminDeleteProofSample(r.id))}
                          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 text-gray-700 hover:bg-gray-50 aria-disabled:opacity-50 aria-disabled:cursor-not-allowed">
                          Hapus sesudah disalin
                        </button>
                      </div>
                      <p className="text-gray-500 break-words">
                        {STEP_PARTS.map((p, i) => (p.code
                          ? <code key={i} className="font-mono text-gray-700 bg-gray-100 rounded px-1">{p.text}</code>
                          : <span key={i}>{p.text}</span>))}
                      </p>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
