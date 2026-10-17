import { useState } from 'react';
import { Icon } from './Icon';
import { chipTones } from './AdvisorChip';
import { openAction } from '../lib/advisorAction';
import { basisLabel } from '../lib/advisorDashboard';
import { dismissOptions } from '../lib/advisorCard';

// Strip AI di satu baris halaman (S12 Langganan; 02-aturan.md §7 "Halaman lain"). Teks dan
// CTA dari server (render.py). `onLocal(aksi)` boleh menangani CTA lebih dulu (mis. route ke
// halaman ini sendiri) dan mengembalikan true; selain itu aksi lewat open-action.
export default function AdvisorRowStrip({ insight, isDark, onLocal, onHide, className = '' }) {
  const [open, setOpen] = useState(false);
  if (!insight) return null;
  const c = chipTones(isDark)[insight.tone] || chipTones(isDark).info;
  const run = (aksi) => { if (!onLocal?.(aksi)) openAction(aksi); };
  const hide = (pilihan) => {
    const kunci = insight.dismiss?.kunci;
    if (!kunci) return;
    onHide?.(kunci);
    openAction({ kind: 'dismiss', payload: { kunci, pilihan } });
  };
  const aksi = insight.aksi || [];
  return (
    <div className={`rounded-xl px-3 py-2 text-[13px] ${className}`} style={{ background: c.bg }}>
      <div className="flex items-start gap-2">
        <Icon name="advisor" size={14} weight="fill" className="mt-0.5 flex-shrink-0" style={{ color: c.text }} />
        <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
          className="flex-1 min-w-0 text-left">
          <p className="font-medium" style={{ color: c.text }}>{insight.judul}</p>
          {open && insight.isi && <p className="mt-0.5" style={{ color: 'var(--text-muted)' }}>{insight.isi}</p>}
        </button>
      </div>
      {open && insight.fakta?.length > 0 && (
        <dl className="mt-2 space-y-1">
          {insight.fakta.map((f, i) => (
            <div key={i} className="flex justify-between gap-3">
              <dt style={{ color: 'var(--text-muted)' }}>{f.label}</dt>
              <dd className="text-right font-medium tabular-nums" style={{ color: 'var(--text)' }}>{f.nilai}</dd>
            </div>
          ))}
        </dl>
      )}
      {open && insight.rincian?.length > 0 && (
        <ul className="mt-2 space-y-1">
          {insight.rincian.map(r => (
            <li key={r.id} style={{ color: 'var(--text-muted)' }}>{r.judul}{r.isi ? ` — ${r.isi}` : ''}</li>
          ))}
        </ul>
      )}
      {aksi.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {aksi.map((a, i) => (
            <button key={`${a.kind}-${i}`} type="button" onClick={() => run(a)}
              className={i === 0 ? 'btn-primary !py-1 !px-3 text-xs' : 'btn-outline !py-1 !px-3 text-xs'}>
              {a.label}
            </button>
          ))}
        </div>
      )}
      {open && (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs" style={{ color: 'var(--text-muted)' }}>
          <span>{basisLabel(insight.dasar)}</span>
          <span className="flex gap-3">
            {dismissOptions(insight).map(o => (
              <button key={o.pilihan} type="button" onClick={() => hide(o.pilihan)} className="font-medium hover:underline">
                {o.label}
              </button>
            ))}
          </span>
        </div>
      )}
    </div>
  );
}
