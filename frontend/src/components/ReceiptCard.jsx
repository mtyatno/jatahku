import { useMemo, useState } from 'react';
import { Icon } from './Icon';
import { confidenceLabel } from '../lib/receiptScan';
import { reconcileItems, splitByEnvelope, isSplit } from '../lib/receiptSplit';

function rupiah(n) {
  return 'Rp ' + Number(n || 0).toLocaleString('id-ID');
}

function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function isInsufficient(msg) {
  const l = String(msg || '').toLowerCase();
  return l.includes('dana tidak cukup') || l.includes('belum ada dana') || l.includes('belum didanai');
}

function isDailyLimit(msg) {
  return String(msg || '').toLowerCase().includes('limit harian');
}

function fmtQty(q) {
  if (q == null) return '';
  return Number.isInteger(q) ? String(q) : String(q).replace('.', ',');
}

// Kartu struk dengan rincian barang: cocokkan Σ barang dengan total struk, dan
// pecah barang ke amplop berbeda (disimpan 1 transaksi per amplop).
export default function ReceiptCard({ entry, envelopes, onChange, onRemove, onFundGroup, onRaiseLimitGroup }) {
  const items = entry.receiptItems || [];
  const adjustments = entry.adjustments || [];
  const rec = useMemo(() => reconcileItems(items, adjustments, entry.amount), [items, adjustments, entry.amount]);
  const split = isSplit(items, entry.envelopeId);
  const groups = useMemo(
    () => (split ? splitByEnvelope(items, entry.amount, entry.envelopeId) : []),
    [split, items, entry.amount, entry.envelopeId],
  );
  const [open, setOpen] = useState(() => rec.status !== 'cocok');
  const locked = Object.keys(entry.savedGroups || {}).length > 0; // sebagian sudah tersimpan
  const doubtful = entry.confidence !== 'tinggi';
  const liveCount = items.filter(it => !it.removed).length;
  const envName = id => {
    const env = envelopes.find(e => e.id === id);
    return env ? `${env.emoji || ''} ${env.name}`.trim() : 'Pilih amplop';
  };

  const patchItem = (id, patch) => onChange(entry.key, {
    receiptItems: items.map(it => (it.id === id ? { ...it, ...patch } : it)),
  });
  // Diedit user → tanda dari scan tidak berlaku lagi.
  const editItem = (id, patch) => patchItem(id, { ...patch, flag: 'ok', note: null, suggestion: null });
  const applySuggestion = (it) => (it.suggestion === 0
    ? patchItem(it.id, { removed: true })
    : patchItem(it.id, { amount: it.suggestion, flag: 'ok', note: 'Diubah sesuai saran', suggestion: null }));
  const addRemainder = () => onChange(entry.key, {
    receiptItems: [...items, {
      id: `x${items.length}-${Date.now()}`, name: 'Lainnya', amount: rec.diff, discount: 0,
      qty: null, unitPrice: null, flag: 'ok', note: 'Ditambahkan agar rincian = total', suggestion: null,
      envelopeId: '', removed: false,
    }],
  });

  const expenseEnvs = envelopes.filter(env => env.purpose !== 'saving' && env.purpose !== 'sinking_fund');

  return (
    <div className="py-3 border-b border-gray-100 last:border-0 space-y-2">
      {/* Kepala struk */}
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={() => onRemove(entry.key)}
          disabled={locked}
          className="shrink-0 text-gray-400 hover:text-red-500 text-sm leading-none p-1 disabled:opacity-30"
          title="Hapus struk"
        >&times;</button>
        <div className="flex-1 min-w-0 space-y-1.5">
          <span className="text-xs text-brand-600 inline-flex items-center gap-1">
            <Icon name="camera" size={12} /> Dari struk
            {doubtful && <span className="text-amber-600"> · {confidenceLabel(entry.confidence)}</span>}
          </span>
          <div className="grid grid-cols-2 sm:grid-cols-12 gap-2">
            <input
              className="input text-sm py-1 col-span-2 sm:col-span-5"
              value={entry.description}
              disabled={locked}
              onChange={e => onChange(entry.key, { description: e.target.value })}
              aria-label="Nama toko"
            />
            <input
              type="date"
              className="input text-xs py-1 sm:col-span-3"
              value={entry.transactionDate || ''}
              max={localToday()}
              disabled={locked}
              onChange={e => onChange(entry.key, { transactionDate: e.target.value || null })}
              aria-label="Tanggal struk"
            />
            <input
              type="number"
              inputMode="numeric"
              min="0"
              className={`input text-sm py-1 font-mono sm:col-span-4 ${doubtful || !entry.amount ? 'border-amber-400 ring-1 ring-amber-200' : ''}`}
              value={entry.amount || ''}
              placeholder="Total"
              disabled={locked}
              onChange={e => onChange(entry.key, { amount: Number(e.target.value) || 0 })}
              aria-label="Total struk"
            />
          </div>
          <select
            className={`input text-sm py-1.5 w-full ${!entry.envelopeId ? 'border-amber-400 ring-1 ring-amber-200' : ''}`}
            value={entry.envelopeId}
            disabled={locked}
            onChange={e => onChange(entry.key, { envelopeId: e.target.value, suggested: false, touched: true })}
            aria-label="Amplop struk"
          >
            <option value="">{split ? 'Amplop untuk barang lainnya' : 'Pilih amplop'}</option>
            {expenseEnvs.map(env => (
              <option key={env.id} value={env.id}>{env.emoji} {env.name}</option>
            ))}
          </select>
          {entry.suggested && <span className="text-xs text-brand-600">disarankan</span>}
        </div>
      </div>

      {/* Status cocok / selisih */}
      <div className={`rounded-lg px-2.5 py-1.5 text-xs flex items-center justify-between gap-2 flex-wrap ${
        rec.status === 'cocok' ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700'}`}
      >
        <span>
          {rec.status === 'cocok'
            ? <>✓ Rincian {liveCount} barang cocok dengan total</>
            : <>Rincian {rupiah(rec.expected)} · total {rupiah(rec.total)} · <strong>{rec.diff > 0 ? 'kurang' : 'lebih'} {rupiah(Math.abs(rec.diff))}</strong></>}
        </span>
        <button type="button" onClick={() => setOpen(o => !o)} className="underline font-medium">
          {open ? 'Sembunyikan' : `Lihat ${liveCount} barang`}
        </button>
      </div>
      {rec.status === 'selisih' && !locked && (
        <div className="text-xs text-amber-700 flex items-center gap-2 flex-wrap">
          <span>
            {rec.diff > 0
              ? 'Mungkin ada barang yang tidak terbaca. Perbaiki barang bertanda, atau:'
              : 'Cek barang bertanda (terbaca dobel?) atau diskon yang terlewat.'}
          </span>
          {rec.diff > 0 && (
            <button type="button" onClick={addRemainder} className="underline font-medium">
              Tambah “Lainnya” {rupiah(rec.diff)}
            </button>
          )}
        </div>
      )}

      {/* Daftar barang */}
      {open && (
        <ul className="border border-gray-100 rounded-lg divide-y divide-gray-100">
          {items.map(it => (it.removed ? null : (
            <li key={it.id} className={`px-2 py-1.5 space-y-1 ${it.flag === 'cek' ? 'bg-amber-50/60' : ''}`}>
              <div className="flex items-center gap-2">
                <input
                  className="input text-xs py-1 flex-1 min-w-0"
                  value={it.name}
                  disabled={locked}
                  onChange={e => patchItem(it.id, { name: e.target.value })}
                  aria-label="Nama barang"
                />
                <input
                  type="number"
                  inputMode="numeric"
                  min="0"
                  className={`input text-xs py-1 font-mono w-24 shrink-0 ${it.flag === 'cek' ? 'border-amber-400 ring-1 ring-amber-200' : ''}`}
                  value={it.amount || ''}
                  disabled={locked}
                  onChange={e => editItem(it.id, { amount: Number(e.target.value) || 0 })}
                  aria-label={`Harga ${it.name}`}
                />
                <button
                  type="button"
                  onClick={() => patchItem(it.id, { removed: true })}
                  disabled={locked}
                  className="shrink-0 text-gray-400 hover:text-red-500 text-sm leading-none p-1 disabled:opacity-30"
                  title="Hapus barang"
                >&times;</button>
              </div>
              <div className="flex items-center gap-x-2 gap-y-1 flex-wrap text-[11px]">
                {it.qty > 1 && it.unitPrice && (
                  <span className="text-gray-400">{fmtQty(it.qty)} × {rupiah(it.unitPrice)}</span>
                )}
                {it.discount > 0 && <span className="text-brand-600">voucher −{rupiah(it.discount)}</span>}
                {it.note && (
                  <span className={it.flag === 'cek' ? 'text-amber-700' : 'text-gray-400'}>
                    {it.flag === 'cek' ? '⚠ ' : ''}{it.note}
                  </span>
                )}
                {it.flag === 'cek' && it.suggestion != null && !locked && (
                  <button type="button" onClick={() => applySuggestion(it)} className="text-brand-600 underline font-medium">
                    {it.suggestion === 0 ? 'Hapus barang ini' : `Pakai ${rupiah(it.suggestion)}`}
                  </button>
                )}
                <select
                  className="ml-auto text-[11px] bg-transparent border border-gray-200 rounded px-1 py-0.5 max-w-[55%]"
                  value={it.envelopeId}
                  disabled={locked}
                  onChange={e => patchItem(it.id, { envelopeId: e.target.value })}
                  aria-label={`Amplop ${it.name}`}
                >
                  <option value="">Ikut amplop struk</option>
                  {expenseEnvs.map(env => (
                    <option key={env.id} value={env.id}>{env.emoji} {env.name}</option>
                  ))}
                </select>
              </div>
            </li>
          )))}
          {adjustments.map((a, i) => (
            <li key={`adj${i}`} className="px-2 py-1 text-[11px] text-gray-500 flex justify-between gap-2">
              <span className="truncate">{a.label}</span>
              <span className="font-mono shrink-0">{a.kind === 'discount' ? '−' : '+'}{rupiah(a.amount)}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Dipecah per amplop */}
      {split && (
        <div className="rounded-lg border border-gray-100 px-2.5 py-2 space-y-1.5 text-xs">
          <div className="text-gray-500">Disimpan sebagai {groups.length} transaksi (diskon & selisih dibagi proporsional):</div>
          {groups.map(g => {
            const err = entry.groupErrors?.[g.envelopeId];
            const saved = entry.savedGroups?.[g.envelopeId];
            return (
              <div key={g.envelopeId || 'none'} className="flex items-center gap-2 flex-wrap">
                <span className={`flex-1 min-w-0 truncate ${!g.envelopeId ? 'text-amber-600' : 'text-gray-700'}`}>
                  {envName(g.envelopeId)} <span className="text-gray-400">· {g.names.length} barang</span>
                </span>
                <span className="font-mono text-gray-700">{rupiah(g.amount)}</span>
                {saved && <span className="text-green-600">tersimpan ✓</span>}
                {entry.raiseLimitEnvs?.[g.envelopeId] && !saved && !err && <span className="text-brand-600">limit ↑</span>}
                {err && (
                  <span className="w-full flex items-center gap-2 flex-wrap text-red-500">
                    <span title={err}>Gagal: {err}</span>
                    {isInsufficient(err) && (
                      <button type="button" onClick={() => onFundGroup(entry.key, g.envelopeId, g.amount)} className="text-brand-600 underline font-medium">Geser</button>
                    )}
                    {isDailyLimit(err) && (
                      <button type="button" onClick={() => onRaiseLimitGroup(entry.key, g.envelopeId)} className="text-brand-600 underline font-medium">Naikkan limit</button>
                    )}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Error simpan (tidak dipecah) */}
      {!split && entry.error && (
        <div className="text-xs text-red-500 flex items-center gap-2 flex-wrap">
          <span>Gagal: {entry.error}</span>
          {isInsufficient(entry.error) && entry.envelopeId && (
            <button type="button" onClick={() => onFundGroup(entry.key, entry.envelopeId, entry.amount)} className="text-brand-600 underline font-medium">Geser</button>
          )}
          {isDailyLimit(entry.error) && entry.envelopeId && (
            <button type="button" onClick={() => onRaiseLimitGroup(entry.key, entry.envelopeId)} className="text-brand-600 underline font-medium">Naikkan limit</button>
          )}
        </div>
      )}
    </div>
  );
}
