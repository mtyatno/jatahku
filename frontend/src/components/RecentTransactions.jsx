import { Link } from 'react-router-dom';
import { formatCurrency, titleCase } from '../lib/utils';
import { localDateStr } from '../lib/kpiVisuals';

// Card "Transaksi terbaru" di Dashboard. Desktop: tabel Keterangan · Amplop · Waktu · Jumlah.
// HP: keterangan + jumlah di atas, toko · amplop · waktu di bawahnya.

// "ROTI TAWAR (Indomaret)" (catatan per barang dari struk) → { title: 'ROTI TAWAR', place: 'Indomaret' }
export function splitDescription(desc) {
  const text = (desc || '').trim();
  const m = text.match(/^(.*\S)\s*\(([^()]+)\)$/);
  return m ? { title: m[1], place: m[2].trim() } : { title: text || 'Tanpa keterangan', place: null };
}

const rupiah = (v) => formatCurrency(v).replace(/\s/g, '');

function when(txn, today) {
  if (txn.transaction_date === today && txn.created_at) {
    return new Date(txn.created_at).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
  }
  return new Date(`${txn.transaction_date}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' });
}

const COLS = 'md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_64px_112px]';

export default function RecentTransactions({ transactions, envelopes, isCurrentPeriod, limit = 6 }) {
  const envById = Object.fromEntries((envelopes || []).map(e => [e.id, e]));
  const today = localDateStr();
  const rows = (transactions || []).slice(0, limit);

  return (
    <section aria-labelledby="transaksi-terbaru-title" className="card !px-4 md:!px-6 !pt-5 md:!pt-6 !pb-3">
      <div className="flex items-baseline justify-between gap-3 pb-3 md:pb-4 px-1">
        <h2 id="transaksi-terbaru-title" className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>
          Transaksi{isCurrentPeriod ? ' terbaru' : ''}
        </h2>
        <Link to="/transactions" className="text-[13px] font-semibold text-brand-600 hover:underline">Semua transaksi</Link>
      </div>

      {rows.length === 0 ? (
        <p className="text-center text-sm py-8" style={{ color: 'var(--text-muted)', borderTop: '1px solid var(--border)' }}>Belum ada transaksi</p>
      ) : (
        <>
          <div className={`hidden md:grid ${COLS} gap-4 px-1 pb-3 text-xs font-medium`} style={{ color: 'var(--text-muted)' }}>
            <span>Keterangan</span>
            <span>Amplop</span>
            <span>Waktu</span>
            <span className="text-right">Jumlah</span>
          </div>
          <ul className="flex flex-col">
            {rows.map(txn => {
              const { title, place } = splitDescription(txn.description);
              const envName = titleCase(envById[txn.envelope_id]?.name || txn.envelope_name || '—');
              const time = when(txn, today);
              return (
                <li key={txn.id} style={{ borderTop: '1px solid var(--border)' }}
                  className={`px-1 py-3 md:py-3.5 flex flex-col gap-1 md:grid ${COLS} md:gap-4 md:items-center`}>
                  <span className="flex items-baseline justify-between gap-3 min-w-0 md:flex-col md:items-start md:gap-1 md:justify-start">
                    <span className="text-[15px] font-semibold truncate min-w-0 max-w-full" style={{ color: 'var(--text)' }}>{title}</span>
                    <span className="md:hidden shrink-0 text-[15px] font-bold tabular-nums" style={{ color: 'var(--text)' }}>−{rupiah(txn.amount)}</span>
                    {place && <span className="hidden md:block text-xs truncate max-w-full" style={{ color: 'var(--text-muted)' }}>{place}</span>}
                  </span>
                  <span className="md:hidden text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                    {[place, envName, time].filter(Boolean).join(' · ')}
                  </span>
                  <span className="hidden md:block text-sm truncate" style={{ color: 'var(--text-muted)' }}>{envName}</span>
                  <span className="hidden md:block text-sm tabular-nums" style={{ color: 'var(--text-muted)' }}>{time}</span>
                  <span className="hidden md:block text-right text-[15px] font-bold tabular-nums" style={{ color: 'var(--text)' }}>−{rupiah(txn.amount)}</span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
