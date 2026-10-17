import { useState } from 'react';
import { Icon } from './Icon';
import { AdvisorChip, InsightPopover, chipTones } from './AdvisorChip';
import { openAction } from '../lib/advisorAction';
import { basisLabel } from '../lib/advisorDashboard';
import { markerActions } from '../lib/transaksiAdvisor';

// Halaman Transaksi AI Advisor (S13, 02-aturan.md §7): banner sesuai filter aktif dan penanda
// baris (HAR-03, DAT-03, DAT-06, TAG-06, TAG-07). Teks dan aksi dirakit server (render.py);
// klik aksi lewat pipa CTA `jatahku:open-action` (S8).

const look = (insight) => ({
  tone: ['danger', 'warn', 'info', 'ok'].includes(insight.tone) ? insight.tone : 'info',
  muted: false,
  text: insight.chip || insight.judul,
});

export function TxnAdvisorBanner({ insight, isDark, search }) {
  const tone = chipTones(isDark)[look(insight).tone];
  const actions = markerActions(insight, search);
  const hide = () => openAction({ kind: 'dismiss', payload: { kunci: insight.dismiss?.kunci || insight.id, pilihan: 'nanti' } });
  return (
    <div className="card !p-4 flex flex-col gap-2" role="status" aria-label="AI Advisor">
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 flex-shrink-0" style={{ color: tone.text }}><Icon name="advisor" size={16} weight="fill" /></span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-sm leading-snug" style={{ color: 'var(--text)' }}>{insight.judul}</p>
          {insight.isi && <p className="mt-0.5 text-[13px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>{insight.isi}</p>}
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 flex-wrap pl-[26px]">
        <div className="flex flex-wrap gap-2">
          {actions.map((a, i) => (
            <button key={`${a.kind}-${i}`} type="button" onClick={() => openAction(a)}
              className={i === 0 ? 'btn-primary !py-1.5 !px-3 text-[13px]' : 'btn-outline !py-1.5 !px-3 text-[13px]'}>
              {a.label}
            </button>
          ))}
        </div>
        <span className="text-xs inline-flex items-center gap-3" style={{ color: 'var(--text-muted)' }}>
          {basisLabel(insight.dasar)}
          {insight.dismiss?.kunci && (
            <button type="button" onClick={hide} className="font-medium hover:underline">Sembunyikan</button>
          )}
        </span>
      </div>
    </div>
  );
}

// Penanda di bawah deskripsi transaksi. Klik → popover (layar lebar) / bottom sheet (HP);
// induk harus `relative`.
export function TxnMarkers({ markers, isDark, phone, search }) {
  const [open, setOpen] = useState(null);
  if (!markers.length) return null;
  const aktif = markers.find(m => m.id === open);
  return (
    <>
      <span className="flex flex-wrap gap-1.5 mt-1">
        {markers.map(m => (
          <AdvisorChip key={m.id} look={look(m)} open={open === m.id} isDark={isDark}
            onClick={() => setOpen(o => (o === m.id ? null : m.id))} />
        ))}
      </span>
      {aktif && (
        <InsightPopover insight={{ ...aktif, aksi: markerActions(aktif, search) }} isDark={isDark} phone={phone}
          onClose={() => setOpen(null)} />
      )}
    </>
  );
}
