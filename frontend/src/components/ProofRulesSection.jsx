import { useState, useEffect, useCallback, useRef, useId } from 'react';
import { api } from '../lib/api';
import {
  RULE_TABS, actionButtons, ruleRows, ruleSummary, voteRows, noteError, decisionBody, actionOutcome, emptyText, nextTab,
} from '../lib/proofRules';

// Bagian "Aturan belajar" kartu Admin Scan Struk. Warna teks baru ≥ 4,5:1 di semua tema terang/gelap: tab aktif
// text-gray-800 (bukan text-brand-600, yang di laut-gelap dan senja-terang di bawah 4,5:1 di atas bg-brand-50),
// peringatan/galat text-amber-600 (tema gelap mencerahkannya di index.css), bukan merah (red-600 di kartu gelap ±3:1).
// Semua logika (kelompok tab, urutan, teks, tombol per status dan ambang, catatan, body keputusan, pesan galat, tombol
// panah tab) ada di lib/proofRules.js; komponen ini hanya memuat data, menyimpan state, dan merender.
// `onLoaded(resp)` memberi kartu daftar terbaru, supaya lencana "N aturan menunggu" ikut berubah sesudah keputusan.
//
// Aksesibilitas: pola tab WAI-ARIA (tabindex bergulir, panah/Home/End, aria-controls, tabpanel); dua wilayah live yang
// selalu ada (status untuk berhasil/409, alert untuk galat) yang teksnya berganti; tombol keputusan memakai
// aria-disabled (bukan disabled) supaya fokus tidak jatuh ke <body> selama permintaan berjalan; sesudah keputusan fokus
// kembali ke judul aturan itu bila masih di tab ini, selain itu ke tab aktif.
const MESSAGE_CLASS = { ok: 'text-green-700', conflict: 'text-amber-600', error: 'text-amber-600' };

export default function ProofRulesSection({ onLoaded }) {
  const uid = useId();
  const tabId = key => `${uid}-tab-${key}`;
  const panelId = `${uid}-panel`;
  const [tab, setTab] = useState('menunggu');
  const [resp, setResp] = useState(undefined);       // undefined = memuat, null = gagal
  const [votes, setVotes] = useState(undefined);
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState({});
  const [message, setMessage] = useState(null);
  const alive = useRef(true);
  const tabRefs = useRef({});
  const headRefs = useRef({});
  const focusAfter = useRef(null);
  useEffect(() => () => { alive.current = false; }, []);

  const load = useCallback(async () => {
    const data = await api.adminProofRules('semua');
    if (!alive.current) return;
    setResp(data);
    if (data) onLoaded?.(data);
  }, [onLoaded]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (tab !== 'suara') return;
    setVotes(undefined);
    api.adminProofVotes().then((data) => { if (alive.current) setVotes(data); });
  }, [tab]);

  // Fokus sesudah keputusan (dijalankan sesudah render yang memuat daftar baru).
  useEffect(() => {
    const id = focusAfter.current;
    if (id === null || busy) return;
    focusAfter.current = null;
    (headRefs.current[id] || tabRefs.current[tab])?.focus();
  });

  function selectTab(key) {
    setTab(key);
    setMessage(null);
  }

  function onTabKey(e) {
    const key = nextTab(tab, e.key);
    if (!key) return;
    e.preventDefault();
    selectTab(key);
    tabRefs.current[key]?.focus();
  }

  async function decide(row, button) {
    if (busy || button.disabled) return;
    setBusy(true);
    setMessage(null);
    const res = await api.adminProofRuleAction(row.id, button.action, decisionBody(row, notes[row.id]));
    const out = actionOutcome(button.action, res);
    if (!alive.current) return;
    if (out.kind === 'ok') setNotes(n => ({ ...n, [row.id]: '' }));
    if (out.reload) await load();
    if (!alive.current) return;
    focusAfter.current = row.id;
    setMessage(out);
    setBusy(false);
  }

  const summary = ruleSummary(resp);
  const rows = ruleRows(resp, tab);
  const vrows = voteRows(votes);
  const polite = message && message.kind !== 'error' ? message : null;
  const urgent = message?.kind === 'error' ? message : null;

  return (
    <div className="mt-4 pt-3 border-t border-gray-100">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h4 className="text-sm font-semibold text-gray-800">Aturan belajar</h4>
        {summary && <p className="text-xs text-gray-500">{summary}</p>}
      </div>
      <div role="tablist" aria-label="Aturan belajar" className="mt-2 flex flex-wrap gap-1">
        {RULE_TABS.map(t => (
          <button key={t.key} type="button" role="tab" id={tabId(t.key)} aria-selected={tab === t.key}
            aria-controls={panelId} tabIndex={tab === t.key ? 0 : -1}
            ref={(el) => { tabRefs.current[t.key] = el; }}
            onClick={() => selectTab(t.key)} onKeyDown={onTabKey}
            className={`px-2.5 py-1 rounded-lg text-xs font-medium ${tab === t.key ? 'bg-brand-50 text-gray-800 font-semibold' : 'text-gray-500 hover:bg-gray-50'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Wilayah live selalu ada; hanya teksnya yang berganti. */}
      <p role="status" aria-live="polite" className={`text-xs ${polite ? MESSAGE_CLASS[polite.kind] : ''}`}>
        {polite && <span className="block mt-2">{polite.text}</span>}
      </p>
      <p role="alert" className="text-xs text-amber-600">
        {urgent && <span className="block mt-2">{urgent.text}</span>}
      </p>

      <div role="tabpanel" id={panelId} aria-labelledby={tabId(tab)} tabIndex={0} className="mt-2">
        {tab === 'suara' ? (
          <>
            {votes === undefined && <p className="text-xs text-gray-500">Memuat…</p>}
            {votes !== undefined && !vrows && <p className="text-xs text-amber-600">Angka suara tidak bisa dimuat. Coba lagi nanti.</p>}
            {vrows?.length === 0 && <p className="text-xs text-gray-500">{emptyText('suara')}</p>}
            {vrows?.length > 0 && (
              <ul className="text-xs">
                {vrows.map(v => (
                  <li key={v.key} className="py-1.5 border-t border-gray-100 flex flex-wrap justify-between gap-x-3">
                    <span className="text-gray-700">{v.app} · {v.kind}</span>
                    <span className="text-gray-500">{v.text}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <>
            {resp === undefined && <p className="text-xs text-gray-500">Memuat…</p>}
            {resp === null && (
              <p className="text-xs text-amber-600">
                Daftar aturan tidak bisa dimuat.{' '}
                <button type="button" className="underline" onClick={() => { setResp(undefined); load(); }}>Muat ulang</button>
              </p>
            )}
            {rows?.length === 0 && <p className="text-xs text-gray-500">{emptyText(tab)}</p>}
            {rows?.length > 0 && (
              <ul>
                {rows.map((r) => {
                  const err = noteError(notes[r.id]);
                  const buttons = actionButtons(r, busy, notes[r.id]);
                  return (
                    <li key={r.id} className="py-2 border-t border-gray-100 text-xs">
                      <h5 tabIndex={-1} ref={(el) => { headRefs.current[r.id] = el; }}
                        className="flex flex-wrap items-baseline gap-x-2 font-normal">
                        <span className="font-semibold text-gray-800">{r.kind}</span>
                        <span className="text-gray-500">{r.app}</span>
                      </h5>
                      <div className="mt-0.5 text-sm text-gray-800 break-words">Label: “{r.label}”</div>
                      <div className="text-gray-500 break-words">Contoh: <span className="font-mono text-gray-700">{r.example}</span></div>
                      {r.warning && <p className="text-amber-600">⚠ {r.warning}</p>}
                      <div className="text-gray-500">{r.meta}</div>
                      {r.threshold && <p className="text-amber-600">{r.threshold}</p>}
                      {r.note && <div className="text-gray-500 break-words">Catatan: {r.note}</div>}
                      {buttons.length > 0 && (
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <input type="text" className="input py-1.5 px-3 text-xs flex-1 min-w-[10rem] placeholder:text-gray-500"
                            placeholder="Catatan (opsional, maks. 200)" aria-label={`Catatan untuk label ${r.label}`}
                            value={notes[r.id] || ''} disabled={busy}
                            onChange={e => setNotes(n => ({ ...n, [r.id]: e.target.value }))} />
                          {buttons.map(b => (
                            <button key={b.action} type="button" aria-disabled={b.disabled}
                              onClick={() => decide(r, b)}
                              className={`px-3 py-1.5 rounded-lg text-xs font-medium aria-disabled:opacity-50 aria-disabled:cursor-not-allowed ${b.action === 'setujui'
                                ? 'bg-green-50 text-green-700 hover:bg-green-100' : 'bg-gray-100 text-gray-700 hover:bg-gray-50'}`}>
                              {b.label}
                            </button>
                          ))}
                        </div>
                      )}
                      {err && <p role="alert" className="mt-1 text-amber-600">{err}</p>}
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  );
}
