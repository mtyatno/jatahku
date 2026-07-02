import { useState } from 'react';
import { Icon } from '../Icon';
import { formatCurrency } from '../../lib/utils';

const TRANSFER = '#7C3AED';

export default function TransferCard({ entry }) {
  const [expanded, setExpanded] = useState(false);
  const transfers = entry.transfers || [];
  const shown = expanded ? transfers : transfers.slice(0, 4);
  return (
    <div className="card border-l-2" style={{ borderLeftColor: TRANSFER }}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h4 className="font-semibold">Transfer Internal</h4>
            <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: 'rgba(124,58,237,0.10)', color: TRANSFER }}>Transfer</span>
          </div>
          <p className="text-xs text-gray-400 mt-0.5">Total {transfers.length} transfer</p>
        </div>
        <p className="font-display font-bold shrink-0" style={{ color: TRANSFER }}>{formatCurrency(entry.amount_total)}</p>
      </div>

      <div className="mt-3 space-y-2">
        {shown.map((t, i) => (
          <div key={i} className="flex items-center gap-2 text-sm">
            <span className="truncate flex-1 text-gray-600">{t.from} <span className="text-gray-400">→</span> {t.to}</span>
            <span className="font-mono text-gray-500 shrink-0">{formatCurrency(Number(t.amount))}</span>
            <span className="text-xs text-gray-400 shrink-0 w-10 text-right">{t.time}</span>
          </div>
        ))}
      </div>

      {transfers.length > 4 && (
        <button onClick={() => setExpanded(v => !v)} className="mt-2 text-xs font-medium hover:underline flex items-center gap-1" style={{ color: TRANSFER }}>
          {expanded ? 'Tampilkan lebih sedikit' : `Lihat semua transfer (${transfers.length})`}
        </button>
      )}
    </div>
  );
}
