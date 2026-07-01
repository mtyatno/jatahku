import { Icon } from './Icon';

const STAT_TINTS = {
  red: { color: '#E24B4A', bg: 'rgba(226,75,74,0.10)' },
  indigo: { color: '#534AB7', bg: 'rgba(83,74,183,0.10)' },
  purple: { color: '#7C3AED', bg: 'rgba(124,58,237,0.10)' },
  orange: { color: '#D97706', bg: 'rgba(217,119,6,0.10)' },
  green: { color: '#0F6E56', bg: 'rgba(15,110,86,0.10)' },
};

export default function StatCard({ icon, tone, label, value, sub }) {
  const t = STAT_TINTS[tone] || STAT_TINTS.green;
  return (
    <div className="card flex items-start gap-3">
      <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0" style={{ background: t.bg }}>
        <Icon name={icon} size={20} color={t.color} />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-gray-400 font-medium">{label}</p>
        <p className="font-display text-xl font-bold mt-0.5 leading-tight" style={{ color: t.color }}>{value}</p>
        <p className="text-xs text-gray-400 mt-0.5 truncate">{sub}</p>
      </div>
    </div>
  );
}
