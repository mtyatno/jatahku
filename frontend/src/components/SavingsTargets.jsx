import { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatShort, titleCase } from '../lib/utils';
import { Icon } from './Icon';

// Card "Target tabungan" di Dashboard, di samping card Amplop pengeluaran.
// Satu baris per amplop tabungan/sinking fund: saldo / target + bar kemajuan.
// Baris diketuk → rincian (kurang berapa, tenggat, perlu per bulan).

function formatMonth(dateStr) {
  if (!dateStr) return null;
  const d = new Date(`${dateStr}T00:00:00`);
  return d.toLocaleDateString('id-ID', { month: 'short', year: 'numeric' });
}

function rowsFrom(envelopes, goals) {
  const goalByEnv = {};
  (goals || []).forEach(g => { goalByEnv[g.envelope_id] = g; });
  return envelopes
    .map(env => {
      const goal = goalByEnv[env.id];
      const balance = goal ? Number(goal.current_balance) : Number(env.free ?? env.remaining ?? 0);
      const target = goal ? Number(goal.target_amount) : 0;
      const pct = goal ? Math.round(goal.progress_pct) : null;
      return { env, goal, balance, target, pct, achieved: !!goal?.is_achieved };
    })
    .sort((a, b) => {
      // Target berjalan dulu (kemajuan terbesar di atas), lalu tanpa target, lalu yang sudah tercapai.
      const rank = (r) => (r.achieved ? 2 : r.goal ? 0 : 1);
      if (rank(a) !== rank(b)) return rank(a) - rank(b);
      return (b.pct ?? 0) - (a.pct ?? 0);
    });
}

function Row({ row, open, onToggle, accent, done, track, inset }) {
  const { env, goal, balance, target, pct, achieved } = row;
  const color = achieved ? done : accent;
  const detailId = `saving-detail-${env.id}`;
  const toTarget = Math.max(target - balance, 0);

  return (
    <li style={{ borderTop: '1px solid var(--border)' }}>
      <button type="button" onClick={onToggle} aria-expanded={open} aria-controls={detailId}
        className="w-full text-left px-1 py-3.5 flex flex-col gap-2.5">
        <span className="flex items-baseline justify-between gap-3">
          <span className="flex items-center gap-1.5 min-w-0">
            <span className="text-[15px] font-semibold truncate" style={{ color: 'var(--text)' }}>{titleCase(env.name)}</span>
            {env.is_personal && <Icon name="lock" size={12} color="var(--text-muted)" />}
          </span>
          <span className="shrink-0 text-sm tabular-nums">
            <b className="font-semibold" style={{ color: 'var(--text)' }}>{formatShort(balance)}</b>
            {goal && <span style={{ color: 'var(--text-muted)' }}> / {formatShort(target)}</span>}
          </span>
        </span>
        {goal ? (
          <span className="flex items-center gap-3">
            <span className="flex-1 h-[6px] rounded-full overflow-hidden" style={{ background: track }}>
              <span className="block h-full rounded-full transition-all duration-500"
                style={{ width: `${Math.min(Math.max(pct, 2), 100)}%`, background: color }} />
            </span>
            <span className="w-16 text-right text-xs tabular-nums" style={{ color: achieved ? done : 'var(--text-muted)', fontWeight: achieved ? 600 : 400 }}>
              {achieved ? 'Tercapai' : `${pct}%`}
            </span>
          </span>
        ) : (
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Belum ada target</span>
        )}
      </button>

      {open && (
        <div id={detailId} className="mt-1 mb-4 mx-1 rounded-xl px-3 py-3 flex flex-col gap-2.5 text-[13px]"
          style={{ background: inset, border: '1px solid var(--border)' }}>
          {goal ? (
            <>
              <span style={{ color: 'var(--text)' }}>
                {achieved ? <>Target <b className="font-semibold">{formatShort(target)}</b> sudah terkumpul.</>
                  : <>Kurang <b className="font-semibold">{formatShort(toTarget)}</b> lagi menuju {formatShort(target)}</>}
              </span>
              {!achieved && (goal.target_date || goal.monthly_needed != null) && (
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {goal.target_date && <>Tenggat {formatMonth(goal.target_date)}</>}
                  {goal.target_date && goal.monthly_needed != null && ' · '}
                  {goal.monthly_needed != null && <span style={{ color: accent }}>≈ {formatShort(goal.monthly_needed)}/bln biar tepat waktu</span>}
                </span>
              )}
            </>
          ) : (
            <span style={{ color: 'var(--text-muted)' }}>Saldo tabungan ini belum punya target.</span>
          )}
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{env.is_personal ? 'Pribadi' : 'Bersama'}</span>
          <Link to="/envelopes"
            className="inline-flex items-center justify-center self-start min-h-[40px] px-3.5 rounded-xl text-[13px] font-semibold"
            style={{ border: '1px solid var(--border)', color: 'var(--text)' }}>
            {goal ? 'Atur target' : '+ Tambah target'}
          </Link>
        </div>
      )}
    </li>
  );
}

export default function SavingsTargets({ envelopes, goals, isDark, accent, done, track }) {
  const [openId, setOpenId] = useState(null);
  const rows = rowsFrom(envelopes, goals);
  const inset = isDark ? 'var(--page)' : 'var(--surface)';

  return (
    <section aria-labelledby="target-tabungan-title" className="card !px-4 md:!px-6 !pt-5 md:!pt-6 !pb-3">
      <div className="flex items-baseline justify-between gap-3 pb-3 px-1">
        <h2 id="target-tabungan-title" className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Target tabungan</h2>
        <Link to="/envelopes" className="text-[13px] font-semibold text-brand-600 hover:underline">Semua</Link>
      </div>
      <ul className="flex flex-col">
        {rows.map(row => (
          <Row key={row.env.id} row={row} open={openId === row.env.id}
            onToggle={() => setOpenId(openId === row.env.id ? null : row.env.id)}
            accent={accent} done={done} track={track} inset={inset} />
        ))}
      </ul>
    </section>
  );
}
