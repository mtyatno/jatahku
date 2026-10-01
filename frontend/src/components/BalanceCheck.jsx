import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency } from '../lib/utils';
import { Icon, EnvelopeIcon, BRAND } from './Icon';
import { toNumber, unassigned, allToOne, canSubmit, toApplyLines, errorText } from '../lib/balanceCheck';

// Modal "Cocokkan saldo" — spec docs/superpowers/specs/2026-09-30-cocokkan-saldo-design.md
// Langkah: input uang riil → hasil (cocok / tak tercatat / lebih) → selesai + undo 6 dtk.

function Stat({ label, value, tone = 'text-gray-800' }) {
  return (
    <div className="rounded-xl bg-gray-50 px-3 py-2 flex items-center justify-between gap-2 sm:block sm:text-center">
      <p className="text-[11px] text-gray-400">{label}</p>
      <p className={`font-display font-bold text-sm whitespace-nowrap ${tone}`}>{value}</p>
    </div>
  );
}

export default function BalanceCheck({ onClose }) {
  const [step, setStep] = useState('input');         // input | result | done
  const [actual, setActual] = useState('');
  const [memberCount, setMemberCount] = useState(1);
  const [preview, setPreview] = useState(null);
  const [lines, setLines] = useState([]);
  const [mainIds, setMainIds] = useState([]);        // baris yang tidak dilipat
  const [showOthers, setShowOthers] = useState(false);
  const [target, setTarget] = useState('');          // tujuan uang lebih
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);          // { token, text, undo? }

  useEffect(() => {
    api.getBalanceCheckStatus().then(s => { if (s?.member_count) setMemberCount(s.member_count); });
  }, []);

  const direction = preview?.direction;
  const gapAbs = preview ? Math.abs(toNumber(preview.gap)) : 0;

  const loadPreview = async () => {
    setBusy(true);
    const res = await api.previewBalanceCheck(actual);
    setBusy(false);
    if (!res.ok) { setError(errorText(res.data, 'Gagal menghitung selisih')); return false; }
    const p = res.data;
    const ls = (p.suggestions || []).map(s => ({
      envelope_id: s.envelope_id, name: s.name, emoji: s.emoji,
      remaining: toNumber(s.remaining), amount: toNumber(s.amount),
    }));
    setPreview(p);
    setLines(ls);
    setMainIds(ls.filter(l => l.amount > 0).map(l => l.envelope_id));
    setShowOthers(false);
    setTarget(p.default_target_envelope_id || '');
    setStep('result');
    return true;
  };

  const check = async () => { setError(null); await loadPreview(); };

  const setLineAmount = (id, value) =>
    setLines(prev => prev.map(l => (l.envelope_id === id ? { ...l, amount: value } : l)));

  const putAllInto = (envelopeId) => {
    const t = (preview?.expense_targets || []).find(x => x.envelope_id === envelopeId);
    if (!t) return;
    setLines(prev => allToOne(prev, {
      envelope_id: t.envelope_id, name: t.name, emoji: t.emoji, remaining: toNumber(t.remaining),
    }, gapAbs));
    setMainIds([envelopeId]);
    setShowOthers(false);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    const res = await api.applyBalanceCheck({
      actual_amount: toNumber(actual),
      expected_app_amount: toNumber(preview.app_amount),
      lines: toApplyLines(direction, lines, target, gapAbs),
    });
    setBusy(false);
    if (res.status === 409) {
      // Data berubah sejak preview (mis. anggota lain baru mencatat) → hitung ulang.
      if (await loadPreview()) setError('Data berubah, selisih sudah dihitung ulang. Cek lagi sebelum simpan.');
      return;
    }
    if (!res.ok) { setError(errorText(res.data, 'Gagal menyimpan')); return; }
    window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
    if (direction === 'match') { onClose(); return; }

    const checkId = res.data.id;
    const token = Date.now();
    setStep('done');
    setToast({
      token,
      text: 'Saldo sudah cocok',
      undo: async () => {
        const u = await api.undoBalanceCheck(checkId);
        if (!u.ok) {
          setToast(t => (t ? { ...t, text: errorText(u.data, 'Gagal membatalkan — coba lagi') } : t));
          return;
        }
        window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
        setToast(null);
        if (!(await loadPreview())) {
          setStep('input');
          setError('Penyesuaian dibatalkan, tapi selisih gagal dihitung ulang. Coba cek lagi.');
        }
      },
    });
    // Tombol Batalkan hanya 6 detik (pola sama dengan bayar langganan). Teks dikembalikan ke
    // "Saldo sudah cocok": undo yang gagal berarti penyesuaian masih berlaku, jadi teks ini akurat.
    setTimeout(() => setToast(t => (t && t.token === token ? { token, text: 'Saldo sudah cocok' } : t)), 6000);
  };

  // Render function (bukan komponen) supaya input tidak re-mount & kehilangan fokus.
  const renderLine = (l) => {
    const after = toNumber(l.remaining) - toNumber(l.amount);
    return (
      <div key={l.envelope_id} className="flex items-center gap-3 border border-gray-100 rounded-xl p-3">
        <EnvelopeIcon value={l.emoji} size={22} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">{l.name}</p>
          {after < 0
            ? <p className="text-xs text-danger-400">akan minus {formatCurrency(Math.abs(after))}</p>
            : <p className="text-xs text-gray-400">sisa setelahnya {formatCurrency(after)}</p>}
        </div>
        <input type="number" inputMode="numeric" min="0"
          className="input font-mono text-right text-sm !py-1 !w-32"
          value={l.amount} onChange={e => setLineAmount(l.envelope_id, e.target.value)} />
      </div>
    );
  };

  if (step === 'input') {
    return (
      <div className="space-y-4">
        <div>
          <label className="text-sm font-medium" htmlFor="bc-actual">Berapa total uangmu sekarang?</label>
          <input id="bc-actual" type="number" inputMode="numeric" min="0" autoFocus
            className="input font-mono mt-1" placeholder="0"
            value={actual} onChange={e => setActual(e.target.value)} />
          <p className="text-xs text-gray-400 mt-1">
            Jumlahkan uang tunai + saldo semua rekening & e-wallet.
            {memberCount > 1 && ' Termasuk uang bersama, tanpa uang pribadi anggota lain.'}
          </p>
        </div>
        {error && <p className="text-sm text-danger-400">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-outline" onClick={onClose}>Batal</button>
          <button type="button" className="btn-primary disabled:opacity-50"
            disabled={busy || actual === '' || toNumber(actual) < 0} onClick={check}>
            {busy ? 'Menghitung…' : 'Cek selisih'}
          </button>
        </div>
      </div>
    );
  }

  if (step === 'done') {
    return (
      <div className="space-y-4 text-center py-2">
        <div className="flex justify-center"><Icon name="check" size={40} weight="fill" color={BRAND} /></div>
        <p className="font-display font-bold text-lg">Saldo sudah cocok</p>
        <p className="text-sm text-gray-500">Penyesuaian tercatat dengan label "Penyesuaian" dan bisa dihapus dari halaman Transaksi.</p>
        {toast && (
          <div className="flex items-center justify-between gap-2 rounded-xl px-3 py-2 bg-gray-900 text-white text-sm text-left">
            <span className="truncate">{toast.text}</span>
            {toast.undo && <button type="button" onClick={toast.undo} className="font-medium text-brand-200 shrink-0">Batalkan</button>}
          </div>
        )}
        <button type="button" className="btn-primary" onClick={onClose}>Tutup</button>
      </div>
    );
  }

  // step === 'result'
  const shown = lines.filter(l => mainIds.includes(l.envelope_id));
  const others = lines.filter(l => !mainIds.includes(l.envelope_id));
  const left = unassigned(gapAbs, lines);
  const expenseTargets = preview.expense_targets || [];
  const gapTone = direction === 'unrecorded_expense' ? 'text-danger-400' : 'text-brand-600';

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <Stat label="Menurut Jatahku" value={formatCurrency(toNumber(preview.app_amount))} />
        <Stat label="Uang riil" value={formatCurrency(toNumber(preview.actual_amount))} />
        <Stat label="Selisih" value={formatCurrency(toNumber(preview.gap))} tone={gapTone} />
      </div>

      {direction === 'match' && (
        <div className="flex items-center gap-2 rounded-xl px-3 py-3" style={{ background: 'rgba(15,110,86,0.08)', color: BRAND }}>
          <Icon name="check" size={20} weight="fill" color={BRAND} />
          <span className="text-sm font-medium">Cocok! Catatanmu sama dengan uang riil.</span>
        </div>
      )}

      {direction === 'unrecorded_expense' && (
        <div className="space-y-3">
          <div>
            <p className="font-semibold">Ada {formatCurrency(gapAbs)} pengeluaran yang belum tercatat</p>
            <p className="text-xs text-gray-400">Saran pembagian dari pola belanjamu 30 hari terakhir. Ubah kalau perlu.</p>
          </div>
          {lines.length === 0 && expenseTargets.length === 0 ? (
            <p className="text-sm text-gray-500">Belum ada amplop pengeluaran. Buat amplop dulu, lalu cocokkan lagi.</p>
          ) : (
            <>
              <div className="space-y-2 max-h-[45vh] overflow-y-auto">
                {shown.map(l => renderLine(l))}
                {others.length > 0 && (
                  <button type="button" className="text-xs text-gray-500 hover:text-brand-600"
                    onClick={() => setShowOthers(v => !v)}>
                    {showOthers ? 'Sembunyikan amplop lain' : `Amplop lain (${others.length})`}
                  </button>
                )}
                {showOthers && others.map(l => renderLine(l))}
              </div>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <p className={`text-sm font-medium ${left === 0 ? 'text-brand-600' : 'text-danger-400'}`}>
                  {left < 0 ? `Kelebihan: ${formatCurrency(Math.abs(left))}` : `Belum dibagi: ${formatCurrency(left)}`}
                </p>
                {expenseTargets.length > 0 && (
                  <select className="input text-sm !py-1 !w-auto" value="" onChange={e => putAllInto(e.target.value)}>
                    <option value="">Taruh semua di satu amplop…</option>
                    {expenseTargets.map(t => <option key={t.envelope_id} value={t.envelope_id}>{t.name}</option>)}
                  </select>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {direction === 'surplus' && (
        <div className="space-y-2">
          <p className="font-semibold">Uangmu {formatCurrency(gapAbs)} lebih banyak dari catatan</p>
          <p className="text-xs text-gray-400">Mungkin ada pemasukan yang belum dicatat, atau sisa amplop Reset dari periode lalu.</p>
          <label className="text-sm block" htmlFor="bc-target">Masukkan ke</label>
          <select id="bc-target" className="input" value={target} onChange={e => setTarget(e.target.value)}>
            <option value="">Pilih amplop…</option>
            {(preview.income_targets || []).map(t => <option key={t.envelope_id} value={t.envelope_id}>{t.name}</option>)}
          </select>
        </div>
      )}

      {error && <p className="text-sm text-danger-400">{error}</p>}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-outline" onClick={() => { setStep('input'); setError(null); }}>Ubah nominal</button>
        <button type="button" className="btn-primary disabled:opacity-50"
          disabled={busy || !canSubmit(direction, gapAbs, lines, target)} onClick={save}>
          {busy ? 'Menyimpan…' : direction === 'match' ? 'Selesai' : 'Simpan penyesuaian'}
        </button>
      </div>
    </div>
  );
}
