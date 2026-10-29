import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { api } from '../lib/api';
import { newRef } from '../lib/ref';
import { currentPeriod, proofBlockReason, wibToday } from '../lib/receiptScan';
import {
  proofHeader, paidLabel, proofWarnings, proofTotal, amountEditable, amountHint, amountFieldText, proofDate, descriptionFor,
  displayNameOf, envelopeChoices, effectiveEnvelope, skipActions, canSave, savePayload, saveOutcome, skipOutcome,
  createSharedLoader, readOnlyNotice, needsRecheck, recheckOutcome,
} from '../lib/proofFormat';
import { READ_WAIT_MS, withTimeout } from '../lib/shareInbox';
import { EnvelopeIcon, Icon } from './Icon';

const NOTE_DEBOUNCE_MS = 600;

// Periode berjalan untuk aturan tanggal dokumen: satu permintaan untuk semua kartu yang terbuka (disimpan 1 menit).
const loadPeriod = createSharedLoader(async () => currentPeriod(await api.getPeriods(1)));

const rupiah = n => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;

// Teks amber di kartu ini selalu amber-600 (#854F0B): tema gelap hanya mencerahkan kelas itu (index.css), sedangkan
// amber-700 bawaan Tailwind tetap gelap dan di bawah 4,5:1 pada kartu tema gelap.
const STATUS_PILL = { success: 'bg-green-50 text-green-700', warning: 'bg-amber-50 text-amber-600', danger: 'bg-red-50 text-red-600' };
const WARNING_TEXT = { danger: 'text-red-600 font-medium', warning: 'text-amber-600' };
const READ_ONLY_TEXT = { danger: 'text-red-600', warning: 'text-amber-600', muted: 'text-gray-500' };
const chipClass = selected => `inline-flex items-center gap-1.5 min-h-[36px] px-3 py-1.5 rounded-full border text-sm
  transition-colors disabled:opacity-50 ${selected
    ? 'border-brand-400 bg-brand-50 text-brand-600 font-medium'
    : 'border-gray-200 text-gray-700 hover:border-brand-400 hover:text-brand-600'}`;

// Kartu konfirmasi satu item Kotak Struk (bukti QRIS/transfer, struk belanja, tidak dikenali): satu transaksi untuk
// total dokumen. Aturannya di lib/proofFormat.js. Tidak ada geser dana dan tidak ada antrean offline di kartu ini.
// - envelopes: daftar amplop (api.getEnvelopeSummary/getEnvelopes); yang ditawarkan disaring proofFormat.envelopeChoices.
// - queued: simpanan item ini masih di antrean offline (form Catat): kartu hanya-baca, tanpa Simpan dan tombol lewati.
// - onSaved({ item, transaction, quotaNotice }) sesudah tercatat; onSkipped({ item, reason, detail }) sesudah dilewati;
//   onBlocked({ item, text }) bila server menolak simpan/lewati (409/404), atau cek ulang struk belanja mendapati struk
//   itu sudah tercatat/dilewati: kartu terkunci, tidak ada tindakan lagi.
// Isian (termasuk client_ref) hidup per item: kartu yang dipakai ulang untuk item lain mulai dari awal.
export default function ProofCard(props) {
  return <ProofCardInner key={props.item?.id} {...props} />;
}

function ProofCardInner({ item, envelopes, queued = false, onSaved, onSkipped, onBlocked }) {
  const ids = useId();
  const refRef = useRef(null);
  if (!refRef.current) refRef.current = newRef();   // client_ref: sekali per kartu
  const [picked, setPicked] = useState(null);     // amplop pilihan user (null = ikut saran yakin)
  const [amountText, setAmountText] = useState(null);   // null = belum disentuh: ikut total dokumen terbaru
  const [dateChoice, setDateChoice] = useState(null);
  const [note, setNote] = useState('');
  const [hint, setHint] = useState(null);         // saran + keterangan terakhir dari POST /saran
  const [renamed, setRenamed] = useState(null);   // merchant sesudah "Ubah nama"
  const [period, setPeriod] = useState(null);
  const [online, setOnline] = useState(() => navigator.onLine !== false);
  const [busy, setBusy] = useState(null);         // 'save' | 'skip'
  const [failure, setFailure] = useState(null);   // saveOutcome / skipOutcome yang gagal
  const [blockedReason, setBlockedReason] = useState(null);   // penolakan 409/404 yang diterima kartu
  const [done, setDone] = useState(null);
  const [renaming, setRenaming] = useState(false);
  const [renameText, setRenameText] = useState('');
  const [renameBusy, setRenameBusy] = useState(false);
  const [renameError, setRenameError] = useState('');
  const busyRef = useRef(false);
  const sentRef = useRef(null);    // payload yang hasilnya belum pasti: dikirim ulang persis sama
  const noteSeq = useRef(0);
  const noteDirty = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;   // StrictMode (dev) memasang efek dua kali
    return () => { mounted.current = false; };
  }, []);

  const merchant = renamed ?? item.merchant ?? null;
  const merchantRef = useRef(merchant);
  merchantRef.current = merchant;

  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  }, []);

  // Periode belum terbaca (gagal / offline saat dibuka) → dicoba lagi saat online.
  useEffect(() => {
    if (period || !online) return undefined;
    let alive = true;
    loadPeriod().then(p => { if (alive && p) setPeriod(p); });
    return () => { alive = false; };
  }, [period, online]);

  // Saran amplop + keterangan untuk catatan (dan nama) saat ini; jawaban lama yang tiba belakangan diabaikan.
  const fetchHint = useCallback(async (noteText, merchantNow) => {
    const seq = ++noteSeq.current;
    const n = noteText.trim();
    const res = await api.kotakSuggest(item.id, n);
    if (!mounted.current || seq !== noteSeq.current || !res) return;
    setHint({ note: n, name: displayNameOf(merchantNow), text: res.description_preview, suggestion: res.suggestion });
  }, [item.id]);

  useEffect(() => {
    if (!noteDirty.current || done) return undefined;
    const timer = setTimeout(() => fetchHint(note, merchantRef.current), NOTE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [note, fetchHint, done]);

  const suggestion = hint ? hint.suggestion : item.suggestion;
  const choices = envelopeChoices(envelopes, suggestion, { first: item.suggestion?.envelope_id ?? null });
  const envelopeId = effectiveEnvelope(choices, { picked, suggestion });
  const preview = hint ? { note: hint.note, name: hint.name, text: hint.text } : undefined;
  const description = descriptionFor(item, { note, preview, merchant });
  const form = { envelopeId, amountText: amountText ?? undefined, dateChoice, period, today: wibToday(), online, blockedReason, queued };
  const verdict = canSave(item, form);
  const readOnly = readOnlyNotice(item, form);
  const header = proofHeader(item);
  const dates = proofDate(item, form);
  const warnings = proofWarnings(item, { blockedReason });
  const skips = skipActions(item, { blockedReason, queued });
  const blockedText = blockedReason || proofBlockReason(item.flags);
  const editable = amountEditable(item);
  const uncertain = failure?.kind === 'uncertain';
  const locked = !!busy || uncertain || !!done;
  const name = displayNameOf(merchant);
  const when = paidLabel(item);

  const change = setter => value => { setFailure(null); setter(value); };

  const save = async ({ raiseLimit = false } = {}) => {
    if (busyRef.current) return;
    let payload = sentRef.current;
    const resend = !!payload;
    if (!payload) {
      const fresh = { ...form, today: wibToday() };   // "Hari ini" = hari saat disimpan
      if (!canSave(item, fresh).ok) return;
      payload = savePayload(item, { ...fresh, description, ref: refRef.current, raiseLimit });
    }
    busyRef.current = true;
    setBusy('save');
    setFailure(null);
    // Struk belanja: dibaca ulang tepat sebelum disimpan (tab/HP lain atau antrean offline bisa sudah mencatatnya;
    // proofFormat.recheckOutcome). Bacaan menggantung → batas waktu, dianggap gagal dibaca; tidak ada yang dikirim.
    if (needsRecheck(item)) {
      const pre = recheckOutcome(await withTimeout(api.kotakItem(item.id), READ_WAIT_MS, null), { resend });
      if (pre) {
        busyRef.current = false;
        if (pre.kind === 'blocked') sentRef.current = null;
        if (!mounted.current) return;
        setBusy(null);
        if (pre.kind === 'blocked') {
          setBlockedReason(pre.text);
          onBlocked?.({ item, text: pre.text });
        } else {
          setFailure(pre);
        }
        return;
      }
    }
    sentRef.current = payload;
    let res = null;
    try {
      res = await api.createTransaction(payload);
    } catch {
      res = null;   // jaringan: hasilnya belum pasti
    }
    const out = saveOutcome(res);
    busyRef.current = false;
    if (out.kind !== 'uncertain') sentRef.current = null;
    if (!mounted.current) return;
    setBusy(null);
    if (out.kind === 'saved') {
      const env = choices.find(c => c.id === payload.envelope_id);
      setDone({ kind: 'saved', envelopeName: env?.name || '', quotaNotice: out.quotaNotice });
      window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
      onSaved?.({ item, transaction: out.transaction, quotaNotice: out.quotaNotice });
    } else if (out.kind === 'blocked') {
      setBlockedReason(out.text);
      onBlocked?.({ item, text: out.text });
    } else {
      setFailure(out);
    }
  };

  const skip = async (reason) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy('skip');
    setFailure(null);
    const out = skipOutcome(await api.kotakSkip(item.id, reason));
    busyRef.current = false;
    if (!mounted.current) return;
    setBusy(null);
    if (out.kind === 'skipped') {
      setDone({ kind: 'skipped' });
      onSkipped?.({ item, reason, detail: out.item });
    } else if (out.kind === 'blocked') {
      setBlockedReason(out.text);
      onBlocked?.({ item, text: out.text });
    } else {
      setFailure(out);
    }
  };

  const startRename = () => {
    setRenameText(name);
    setRenameError('');
    setRenaming(true);
  };

  const submitRename = async (e) => {
    e.preventDefault();
    if (renameBusy || locked || !merchant?.id) return;   // simpan belum pasti: nama dikunci seperti isian lain
    setRenameBusy(true);
    setRenameError('');
    const res = await api.kotakRenameMerchant(merchant.id, renameText.trim());
    if (!mounted.current) return;
    setRenameBusy(false);
    if (!res.ok) {
      setRenameError(typeof res.data?.detail === 'string' && res.data.detail ? res.data.detail : 'Nama tidak bisa disimpan.');
      return;
    }
    const next = { ...merchant, ...res.data };
    setRenamed(next);
    setRenaming(false);
    fetchHint(note, next);   // keterangan dan saran dengan nama baru
  };

  if (done) {
    return (
      <section className="card p-4 flex items-start gap-2" aria-label={header.badge} role="status">
        <Icon name={done.kind === 'saved' ? 'check' : 'skip'} size={20} className={done.kind === 'saved' ? 'text-brand-600' : 'text-gray-400'} />
        <div className="min-w-0 space-y-0.5">
          <p className="text-sm font-medium text-gray-800">
            {done.kind === 'saved' ? (done.envelopeName ? `Tercatat di ${done.envelopeName}.` : 'Tercatat.') : 'Dilewati.'}
          </p>
          <p className="text-xs text-gray-500 truncate">{[header.badge, name, when].filter(Boolean).join(' · ')}</p>
          {done.quotaNotice && <p className="text-xs text-amber-600">{done.quotaNotice}</p>}
        </div>
      </section>
    );
  }

  // Belum siap / sudah selesai, atau simpanannya di antrean offline: badge dan alasannya saja (proofFormat.readOnlyNotice).
  if (readOnly) {
    const total = proofTotal(item);
    return (
      <section className="card p-4 space-y-1" aria-label={header.badge}>
        <span className="inline-flex rounded-full bg-brand-50 text-brand-600 px-2.5 py-0.5 text-xs font-semibold">{header.badge}</span>
        {readOnly.queued && (
          <p className="text-xs text-gray-500 truncate">{[total ? rupiah(total) : null, name, when].filter(Boolean).join(' · ')}</p>
        )}
        <p className={`text-sm ${READ_ONLY_TEXT[readOnly.tone] || ''}`}>{readOnly.text}</p>
      </section>
    );
  }

  const amountShown = editable ? null : proofTotal(item);
  const amountDoubt = amountHint(item);
  const reasonShown = !verdict.ok && !uncertain && verdict.reason !== blockedText ? verdict.reason : null;
  const sameSkip = skips.filter(s => s.reason === 'duplikat');
  const otherSkips = skips.filter(s => s.reason !== 'duplikat');

  return (
    <section className="card p-4 space-y-3" aria-label={`${header.badge}${amountShown ? `, ${rupiah(amountShown)}` : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 text-brand-600 px-2.5 py-0.5 text-xs font-semibold">
          {header.badge}
        </span>
        {header.statusText && (
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_PILL[header.statusTone] || ''}`}>{header.statusText}</span>
        )}
      </div>

      {editable ? (
        <div>
          <label htmlFor={`${ids}-amount`} className="block text-xs text-gray-500 mb-1">
            Nominal{amountDoubt && <span className="text-amber-600"> · {amountDoubt}</span>}
          </label>
          <input
            id={`${ids}-amount`}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            className={`input font-mono text-xl font-semibold ${amountDoubt ? 'border-amber-400 ring-1 ring-amber-200' : ''}`}
            value={amountFieldText(item, amountText)}
            placeholder="0"
            onChange={e => change(setAmountText)(e.target.value)}
            disabled={locked || !!blockedText}
          />
        </div>
      ) : (
        <p className="font-display text-3xl font-bold text-gray-900">{rupiah(amountShown)}</p>
      )}

      <div className="space-y-1">
        {(name || (merchant?.id && !renaming)) && (
          <div className="flex items-baseline gap-2 flex-wrap">
            {name && <span className="font-semibold text-gray-800 break-words">{name}</span>}
            {merchant?.id && !renaming && !blockedText && (
              <button type="button" onClick={startRename} disabled={locked}
                className="text-xs text-brand-600 underline font-medium px-1 py-2 disabled:opacity-50">
                Ubah nama
              </button>
            )}
          </div>
        )}
        {renaming && (
          <form onSubmit={submitRename} className="space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <input
                className="input py-1.5 flex-1 min-w-[10rem]"
                value={renameText}
                maxLength={60}
                onChange={e => setRenameText(e.target.value)}
                aria-label="Nama tampilan"
                autoFocus
                disabled={renameBusy || locked}
              />
              <button type="submit" disabled={renameBusy || locked} className="text-sm text-brand-600 font-medium underline px-1 py-2 disabled:opacity-50">
                {renameBusy ? 'Menyimpan…' : 'Simpan nama'}
              </button>
              <button type="button" disabled={renameBusy} onClick={() => setRenaming(false)} className="text-sm text-gray-500 underline px-1 py-2">
                Batal
              </button>
            </div>
            {renameError && <p className="text-xs text-red-600" role="alert">{renameError}</p>}
          </form>
        )}
        {when && <p className="text-sm text-gray-500">{when}</p>}
      </div>

      {dates.notice && (
        <div className="space-y-1.5">
          <p className="text-sm text-amber-600">{dates.notice.text}</p>
          {dates.choices.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap" role="group" aria-label="Tanggal catat">
              {dates.choices.map(c => (
                <button key={c.key} type="button" aria-pressed={c.picked} disabled={locked}
                  onClick={() => change(setDateChoice)(c.key)} className={chipClass(c.picked)}>
                  {c.picked && <Icon name="check" size={14} />}
                  {c.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {!blockedText && (
        <div role="group" aria-labelledby={`${ids}-env`}>
          <p id={`${ids}-env`} className="text-xs text-gray-500 mb-1.5">Amplop</p>
          <div className="flex flex-wrap gap-2">
            {choices.map(c => {
              const selected = c.id === envelopeId;
              return (
                <button key={c.id} type="button" aria-pressed={selected} disabled={locked}
                  onClick={() => change(setPicked)(c.id)} className={chipClass(selected)}>
                  {selected ? <Icon name="check" size={14} /> : <EnvelopeIcon value={c.emoji} size={16} />}
                  <span>{c.name}</span>
                  {c.suggested && <span className="text-xs text-brand-600 font-normal">· disarankan</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {!blockedText && (
        <div>
          <label htmlFor={`${ids}-note`} className="block text-xs text-gray-500 mb-1">Catatan</label>
          <input
            id={`${ids}-note`}
            className="input"
            placeholder="bakso 2, es teh (opsional)"
            maxLength={200}
            value={note}
            onChange={e => { noteDirty.current = true; setNote(e.target.value); }}
            disabled={locked}
          />
          <p className="text-xs text-gray-500 mt-1 break-words">Keterangan: {description}</p>
        </div>
      )}

      {warnings.length > 0 && (
        <ul id={`${ids}-warn`} className="space-y-1">
          {warnings.map((w, i) => (
            <li key={`${i}-${w.text}`} className={`flex items-start gap-1.5 text-sm ${WARNING_TEXT[w.tone] || ''}`}>
              <Icon name="warning" size={16} className="shrink-0 mt-0.5" />
              <span>{w.text}</span>
            </li>
          ))}
        </ul>
      )}

      {failure && (
        <div role="alert" className={`rounded-xl border px-3 py-2 text-sm space-y-2 ${uncertain
          ? 'border-amber-200 bg-amber-50 text-amber-600' : 'border-red-200 bg-red-50 text-red-600'}`}>
          <p>{failure.text}</p>
          {failure.kind === 'limit' && (
            <button type="button" disabled={!!busy} onClick={() => save({ raiseLimit: true })}
              className="bg-brand-600 hover:bg-brand-900 text-white rounded-lg px-3 py-2 text-xs font-medium disabled:opacity-50">
              Catat, naikkan limit hari ini
            </button>
          )}
          {failure.kind === 'funds' && <p className="text-xs">Pilih amplop lain lalu Simpan lagi.</p>}
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={() => save()}
          disabled={!!busy || (uncertain ? !online : !verdict.ok)}
          aria-describedby={[warnings.length ? `${ids}-warn` : null, reasonShown ? `${ids}-reason` : null]
            .filter(Boolean).join(' ') || undefined}
          className="btn-primary disabled:opacity-50"
        >
          {busy === 'save' ? 'Menyimpan…' : 'Simpan'}
        </button>
        {sameSkip.map(s => (
          <button key={s.reason} type="button" disabled={locked || !online} onClick={() => skip(s.reason)} className="btn-outline disabled:opacity-50">
            {s.label}
          </button>
        ))}
        <span className="flex-1" />
        {otherSkips.map(s => (
          <button key={s.reason} type="button" disabled={locked || !online} onClick={() => skip(s.reason)}
            className="text-sm text-gray-500 hover:text-gray-700 underline px-2 py-2 disabled:opacity-50">
            {s.label}
          </button>
        ))}
      </div>
      <p id={`${ids}-reason`} className="text-xs text-gray-500 empty:hidden" aria-live="polite">{reasonShown}</p>
    </section>
  );
}
