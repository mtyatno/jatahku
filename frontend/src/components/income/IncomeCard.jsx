import { EnvelopeIcon, Icon, SAVING, BRAND } from '../Icon';
import { formatCurrency } from '../../lib/utils';

export default function IncomeCard({ income }) {
  const total = Number(income.amount) || 0;
  const allocs = income.allocations || [];
  return (
    <div className="card border-l-2" style={{ borderLeftColor: BRAND }}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex items-center gap-2">
          <h4 className="font-semibold truncate">{income.source}</h4>
          <span className="text-xs px-2 py-0.5 rounded-full shrink-0" style={{ background: 'rgba(15,110,86,0.10)', color: BRAND }}>Income</span>
        </div>
        <div className="text-right shrink-0">
          <p className="font-display font-bold text-brand-600">{formatCurrency(total)}</p>
          <p className="text-xs text-gray-400">{income.time}</p>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2 text-xs rounded-lg px-3 py-2" style={{ background: 'rgba(15,110,86,0.08)', color: BRAND }}>
        <Icon name="check" size={14} weight="fill" color={BRAND} />
        <span>100% dialokasikan ke {allocs.length} amplop</span>
      </div>

      <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
        {allocs.map((a, i) => {
          const pct = total > 0 ? Math.round(Number(a.amount) / total * 100) : 0;
          const isSaving = a.purpose === 'saving' || a.purpose === 'sinking_fund';
          const barColor = isSaving ? SAVING : BRAND;
          return (
            <div key={i} className="flex items-center gap-2 min-w-0">
              <EnvelopeIcon value={a.emoji} size={20} />
              <div className="flex-1 min-w-0">
                <div className="flex justify-between gap-2">
                  <span className="text-sm truncate">{a.envelope}</span>
                  <span className="text-xs text-gray-400 shrink-0">{pct}%</span>
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <div className="h-1.5 rounded-full flex-1 bg-gray-100 overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${Math.max(pct, 2)}%`, background: barColor }} />
                  </div>
                  <span className="text-xs font-mono text-gray-500 shrink-0">{formatCurrency(Number(a.amount))}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
