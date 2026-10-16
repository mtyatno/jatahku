import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from './Icon';
import { openAction } from '../lib/advisorAction';
import { basisLabel, popoverActions } from '../lib/advisorDashboard';

// Chip AI di kartu KPI Beranda (01-desain.md "Chip AI di 6 kartu KPI", 02-aturan.md §7).
// Klik chip → popover di bawah kartu (layar lebar) atau bottom sheet (HP). Isi popover
// sudah dirakit server (render.py); di sini hanya ditampilkan.

const CHIP_TONES = {
  light: {
    danger: { text: '#DC2626', bg: 'rgba(220,38,38,0.10)' },
    warn: { text: '#B45309', bg: 'rgba(217,119,6,0.12)' },
    info: { text: '#2563EB', bg: 'rgba(37,99,235,0.10)' },
    ok: { text: '#047857', bg: 'rgba(16,185,129,0.12)' },
  },
  dark: {
    danger: { text: '#F87171', bg: 'rgba(248,113,113,0.16)' },
    warn: { text: '#FBBF24', bg: 'rgba(251,191,36,0.14)' },
    info: { text: '#93C5FD', bg: 'rgba(147,197,253,0.14)' },
    ok: { text: '#6EE7B7', bg: 'rgba(110,231,183,0.14)' },
  },
};

export const chipTones = (isDark) => CHIP_TONES[isDark ? 'dark' : 'light'];

export function useIsPhone() {
  const query = '(max-width: 767px)';
  const [phone, setPhone] = useState(() => typeof window !== 'undefined' && window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return undefined;
    const on = () => setPhone(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return !!phone;
}

// Redam: tanpa latar dan tanpa ✦, hanya teks dengan garis tepi tipis.
export function AdvisorChip({ look, open, onClick, isDark }) {
  const c = chipTones(isDark)[look.tone];
  const style = look.muted
    ? { color: 'var(--text-muted)', background: 'transparent', boxShadow: 'inset 0 0 0 1px var(--border)' }
    : { color: c.text, background: c.bg };
  return (
    <button type="button" onClick={onClick} aria-expanded={open} aria-haspopup="dialog"
      className="text-xs font-semibold px-2.5 py-1 rounded-full whitespace-nowrap inline-flex items-center gap-1 hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-200"
      style={style}>
      {!look.muted && <Icon name="advisor" size={12} weight="fill" />}
      {look.text}
    </button>
  );
}

function InsightBody({ insight, stamp, tone, onClose }) {
  const actions = popoverActions(insight);
  const run = (aksi) => { onClose(); openAction(aksi); };
  const hide = () => {
    onClose();
    if (insight.dismiss?.kunci) openAction({ kind: 'dismiss', payload: { kunci: insight.dismiss.kunci, pilihan: 'nanti' } });
  };
  return (
    <>
      <div className="flex items-start justify-between gap-3">
        <p className="font-semibold text-[15px] leading-snug" style={{ color: 'var(--text)' }}>
          <span className="inline-block w-2 h-2 rounded-full mr-2 align-middle" style={{ background: tone.text }} aria-hidden="true" />
          {insight.judul}
        </p>
        <button type="button" onClick={onClose} aria-label="Tutup"
          className="-mr-1 -mt-0.5 p-1 rounded-md hover:bg-black/5 flex-shrink-0" style={{ color: 'var(--text-muted)' }}>
          <Icon name="close" size={16} />
        </button>
      </div>
      {insight.isi && <p className="mt-1.5 text-sm leading-relaxed" style={{ color: 'var(--text)' }}>{insight.isi}</p>}
      {insight.fakta?.length > 0 && (
        <dl className="mt-3 space-y-1.5 text-[13px]">
          {insight.fakta.map((f, i) => (
            <div key={i} className="flex justify-between gap-3">
              <dt style={{ color: 'var(--text-muted)' }}>{f.label}</dt>
              <dd className="text-right font-medium tabular-nums" style={{ color: 'var(--text)' }}>{f.nilai}</dd>
            </div>
          ))}
        </dl>
      )}
      {insight.rincian?.length > 0 && (
        <ul className="mt-3 space-y-1 text-[13px]" style={{ color: 'var(--text-muted)' }}>
          {insight.rincian.map(r => <li key={r.id}>· {r.judul}</li>)}
        </ul>
      )}
      {actions.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {actions.map((a, i) => (
            <button key={`${a.kind}-${i}`} type="button" onClick={() => run(a)}
              className={i === 0 ? 'btn-primary !py-2 !px-3.5 text-sm' : 'btn-outline !py-2 !px-3.5 text-sm'}>
              {a.label}
            </button>
          ))}
        </div>
      )}
      <div className="mt-3 pt-3 flex items-center justify-between gap-3 text-xs border-t" style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
        <span>{[basisLabel(insight.dasar), stamp].filter(Boolean).join(' · ')}</span>
        {insight.dismiss?.kunci && (
          <button type="button" onClick={hide} className="font-medium hover:underline flex-shrink-0">Sembunyikan</button>
        )}
      </div>
    </>
  );
}

// Layar lebar: absolut di bawah kartu, selebar kartu (induk harus `relative`).
// HP: bottom sheet lewat portal, ditutup dengan latar atau tombol tutup.
export function InsightPopover({ insight, stamp, isDark, phone, onClose }) {
  const tone = chipTones(isDark)[insight.tone] || chipTones(isDark).info;
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (phone) {
    return createPortal(
      <div className="fixed inset-0 z-50 flex items-end" role="dialog" aria-modal="true" aria-label={insight.judul}>
        <div className="absolute inset-0 bg-black/40" onClick={onClose} />
        <div className="relative w-full rounded-t-2xl px-4 pt-3 pb-[calc(1rem+env(safe-area-inset-bottom))] max-h-[85vh] overflow-y-auto shadow-xl"
          style={{ background: 'var(--card-bg)' }}>
          <div className="mx-auto mb-3 h-1 w-10 rounded-full" style={{ background: 'var(--border)' }} aria-hidden="true" />
          <InsightBody insight={insight} stamp={stamp} tone={tone} onClose={onClose} />
        </div>
      </div>,
      document.body,
    );
  }
  return (
    <div role="dialog" aria-label={insight.judul}
      className="absolute left-0 right-0 top-full mt-2 z-30 rounded-xl p-4 shadow-xl text-left"
      style={{ background: 'var(--card-bg)', border: '1px solid var(--border)' }}>
      <InsightBody insight={insight} stamp={stamp} tone={tone} onClose={onClose} />
    </div>
  );
}
