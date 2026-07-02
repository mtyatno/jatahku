import { useState, useMemo } from 'react';
import { Icon } from '../Icon';
import IncomeCard from './IncomeCard';
import TransferCard from './TransferCard';

const BRAND = '#0F6E56';
const TRANSFER = '#7C3AED';
const MONTHS_ID = ['JAN', 'FEB', 'MAR', 'APR', 'MEI', 'JUN', 'JUL', 'AGU', 'SEP', 'OKT', 'NOV', 'DES'];

function buildEntries(incomes) {
  const incomeEntries = [];
  const transferByDate = {};
  for (const inc of incomes) {
    if (inc.type === 'transfer') {
      if (!inc.transfer) continue;
      (transferByDate[inc.date] = transferByDate[inc.date] || []).push({ ...inc.transfer, time: inc.time });
    } else {
      incomeEntries.push({ kind: 'income', date: inc.date, ts: `${inc.date} ${inc.time}`, income: inc });
    }
  }
  const transferEntries = Object.entries(transferByDate).map(([date, transfers]) => {
    const times = transfers.map(t => t.time).sort();
    const amount_total = transfers.reduce((s, t) => s + Number(t.amount || 0), 0);
    const latest = times[times.length - 1] || '';
    return { kind: 'transfer', date, ts: `${date} ${latest}`, transfers, amount_total };
  });
  return [...incomeEntries, ...transferEntries].sort((a, b) => b.ts.localeCompare(a.ts));
}

function DateBadge({ date, kind }) {
  const d = new Date(date + 'T00:00:00');
  const color = kind === 'transfer' ? TRANSFER : BRAND;
  const bg = kind === 'transfer' ? 'rgba(124,58,237,0.10)' : 'rgba(15,110,86,0.10)';
  return (
    <div className="flex flex-col items-center w-12 sm:w-14 shrink-0">
      <div className="w-10 h-10 rounded-full flex items-center justify-center" style={{ background: bg }}>
        <Icon name={kind === 'transfer' ? 'transfer' : 'calendar'} size={18} color={color} />
      </div>
      <span className="font-display font-bold text-sm mt-1 leading-none">{d.getDate()}</span>
      <span className="text-[10px] text-gray-400 leading-tight">{MONTHS_ID[d.getMonth()]}</span>
      <span className="text-[10px] text-gray-400 leading-tight">{d.getFullYear()}</span>
    </div>
  );
}

export default function IncomeHistory({ incomes, periods, periodIdx, onPeriodChange }) {
  const [tab, setTab] = useState('semua');
  const [chip, setChip] = useState(null);
  const [search, setSearch] = useState('');

  const entries = useMemo(() => buildEntries(incomes), [incomes]);
  const sources = useMemo(
    () => [...new Set(incomes.filter(i => i.type !== 'transfer').map(i => i.source))],
    [incomes],
  );

  const q = search.trim().toLowerCase();
  const filtered = entries.filter(e => {
    if (tab === 'income' && e.kind !== 'income') return false;
    if (tab === 'transfer' && e.kind !== 'transfer') return false;
    if (chip && (e.kind !== 'income' || e.income.source !== chip)) return false;
    if (q) {
      const hay = e.kind === 'income'
        ? `${e.income.source} ${(e.income.allocations || []).map(a => a.envelope).join(' ')}`.toLowerCase()
        : e.transfers.map(t => `${t.from} ${t.to}`).join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  return (
    <div className="space-y-4">
      <h2 className="font-display font-bold text-lg">Riwayat income</h2>

      <div className="flex flex-col sm:flex-row gap-2">
        <div className="relative flex-1">
          <span className="absolute left-3 top-1/2 -translate-y-1/2"><Icon name="search" size={16} color="#9ca3af" /></span>
          <input className="input pl-9" placeholder="Cari income, sumber, atau amplop..." value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        {periods.length > 0 && (
          <select className="input sm:w-56" value={periodIdx} onChange={e => onPeriodChange(Number(e.target.value))}>
            {periods.map((p, i) => <option key={i} value={i}>{p.label}</option>)}
          </select>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {['semua', 'income', 'transfer'].map(t => (
          <button key={t} onClick={() => { setTab(t); setChip(null); }}
            className={`text-xs px-3 py-1 rounded-full capitalize transition-colors ${tab === t && !chip ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500 hover:bg-gray-100'}`}>
            {t}
          </button>
        ))}
        {sources.map(s => (
          <button key={s} onClick={() => { setChip(chip === s ? null : s); setTab('semua'); }}
            className={`text-xs px-3 py-1 rounded-full transition-colors ${chip === s ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500 hover:bg-gray-100'}`}>
            {s}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="card text-center py-8 text-gray-400">Belum ada income di periode ini.</div>
      ) : (
        <div className="space-y-3">
          {filtered.map((e, i) => (
            <div key={i} className="flex gap-3">
              <DateBadge date={e.date} kind={e.kind} />
              <div className="flex-1 min-w-0">
                {e.kind === 'income' ? <IncomeCard income={e.income} /> : <TransferCard entry={e} />}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-start gap-2 text-xs text-gray-400 rounded-xl px-4 py-3 bg-gray-50">
        <Icon name="info" size={15} color="#9ca3af" />
        <span>Setiap income yang masuk akan otomatis dialokasikan ke amplop sesuai pengaturan atau aturan alokasi kamu.</span>
      </div>
    </div>
  );
}
