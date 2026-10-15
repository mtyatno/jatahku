import { Link } from 'react-router-dom';
import { formatShort } from '../lib/utils';
import { monthlyEquivalentTotal, sortForPayment } from '../lib/subscriptionStatus';

// Card "Langganan" di Dashboard: total setara per bulan + daftar langganan aktif dengan status
// pembayarannya (status dihitung server: overdue / due / paid / upcoming).

const RED = '#E24B4A';    // danger-400
const AMBER = '#BA7517';  // amber-400

const fmtDay = (d) => new Date(`${d}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' });

export function subscriptionLine(item) {
  const day = item.next_run ? fmtDay(item.next_run) : null;
  switch (item.status) {
    case 'overdue': return { text: `Jatuh tempo ${day} · telat`, color: RED };
    case 'due': return { text: `Belum bayar · jatuh tempo ${day}`, color: AMBER };
    case 'paid': return { text: `Lunas · berikutnya ${day}`, color: 'var(--text-muted)' };
    default: return { text: `Jatuh tempo ${day}`, color: 'var(--text-muted)' };
  }
}

const FREQ = { weekly: '/mgg', yearly: '/thn' };

export default function SubscriptionsCard({ items, limit = 5 }) {
  const active = (items || []).filter(i => i.is_active !== false);
  // Telat dulu, lalu belum bayar, belum jatuh tempo, lunas; dalam status yang sama, jatuh tempo terdekat dulu.
  const rows = sortForPayment([...active].sort((a, b) => (a.next_run || '').localeCompare(b.next_run || '')))
    .slice(0, limit);
  const total = monthlyEquivalentTotal(active);
  const more = active.length - rows.length;

  return (
    <section aria-labelledby="langganan-title" className="card !px-4 md:!px-6 !pt-5 md:!pt-6 !pb-3">
      <div className="flex items-baseline justify-between gap-3 pb-3 px-1">
        <h2 id="langganan-title" className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Langganan</h2>
        {active.length > 0 && (
          <span className="text-[13px] tabular-nums" style={{ color: 'var(--text-muted)' }}>{formatShort(total)}/bln</span>
        )}
      </div>

      {active.length === 0 ? (
        <div className="flex flex-col items-center gap-1.5 text-center py-7 px-3" style={{ borderTop: '1px solid var(--border)' }}>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Belum ada langganan atau tagihan rutin.</p>
          <Link to="/langganan" className="text-sm font-semibold text-brand-600">+ Tambah langganan</Link>
        </div>
      ) : (
        <ul className="flex flex-col">
          {rows.map(item => {
            const line = subscriptionLine(item);
            return (
              <li key={item.id} style={{ borderTop: '1px solid var(--border)' }}>
                <Link to="/langganan" className="flex items-center justify-between gap-3 px-1 py-3.5">
                  <span className="flex flex-col gap-1 min-w-0">
                    <span className="text-[15px] font-semibold truncate" style={{ color: 'var(--text)' }}>{item.description}</span>
                    <span className="text-xs truncate" style={{ color: line.color }}>{line.text}</span>
                  </span>
                  <span className="shrink-0 text-[15px] font-bold tabular-nums" style={{ color: 'var(--text)' }}>
                    {formatShort(item.amount)}
                    {FREQ[item.frequency] && <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>{FREQ[item.frequency]}</span>}
                  </span>
                </Link>
              </li>
            );
          })}
          {more > 0 && (
            <li style={{ borderTop: '1px solid var(--border)' }} className="px-1 pt-3 pb-1">
              <Link to="/langganan" className="text-[13px] font-semibold text-brand-600 hover:underline">+{more} langganan lainnya</Link>
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
