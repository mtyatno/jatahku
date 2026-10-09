import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, AreaChart, Area, CartesianGrid } from 'recharts';

function formatDate(isoStr) {
  if (!isoStr) return '-';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return '-';
    return d.toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' });
  } catch {
    return '-';
  }
}

function timeAgo(isoStr) {
  if (!isoStr) return null;
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return null;
    const now = new Date();
    const diffSec = Math.floor((now - d) / 1000);
    if (diffSec < 60) return 'baru saja';
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m lalu`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours}j lalu`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays === 1) return 'kemarin';
    if (diffDays < 7) return `${diffDays}h lalu`;
    if (diffDays < 30) return `${Math.floor(diffDays / 7)} mg lalu`;
    if (diffDays < 365) return `${Math.floor(diffDays / 30)} bln lalu`;
    return `${Math.floor(diffDays / 365)} thn lalu`;
  } catch {
    return null;
  }
}

const STATUS_CONFIG = {
  active: { label: 'Aktif', bg: 'bg-emerald-50 text-emerald-700 border-emerald-200', dot: 'bg-emerald-500', desc: 'Ada transaksi ≤ 7 hari terakhir' },
  idle: { label: 'Jarang', bg: 'bg-amber-50 text-amber-700 border-amber-200', dot: 'bg-amber-500', desc: 'Transaksi 8–30 hari terakhir' },
  dormant: { label: 'Dormant', bg: 'bg-rose-50 text-rose-700 border-rose-200', dot: 'bg-rose-500', desc: '> 30 hari tidak ada transaksi' },
  no_txn: { label: 'Belum Catat', bg: 'bg-slate-100 text-slate-600 border-slate-200', dot: 'bg-slate-400', desc: '0 transaksi sejak daftar' },
  banned: { label: 'Banned', bg: 'bg-red-100 text-red-800 border-red-300', dot: 'bg-red-700', desc: 'Akun diblokir' },
};

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 shadow-sm">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-sm font-semibold" style={{color: p.color}}>{p.name}: {typeof p.value === 'number' && p.value > 1000 ? formatCurrency(p.value) : p.value}</p>
      ))}
    </div>
  );
}

function KPI({ label, value, sub, color }) {
  return (
    <div className="card">
      <p className="text-xs text-gray-400">{label}</p>
      <p className={`font-display text-2xl font-bold mt-1 ${color || ''}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

function UserRow({ u, onAction, onSelectUser, onQuickDm }) {
  const [loading, setLoading] = useState(false);
  const statusCfg = STATUS_CONFIG[u.status] || STATUS_CONFIG.dormant;
  const lastActiveStr = timeAgo(u.last_txn_at);

  const doAction = async (e, action) => {
    e.stopPropagation();
    if (action === 'ban' && !confirm(`Ban ${u.name}?`)) return;
    setLoading(true);
    await onAction(u.id, action);
    setLoading(false);
  };

  const handleDmClick = (e) => {
    e.stopPropagation();
    onQuickDm(u.id);
  };

  return (
    <div
      onClick={() => onSelectUser(u.id)}
      className="group p-3 sm:p-3.5 border-b border-gray-100 last:border-0 hover:bg-emerald-50/20 transition-all cursor-pointer rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-3"
    >
      <div className="flex items-start gap-3 min-w-0">
        <div className="relative shrink-0 mt-0.5">
          <div className="w-10 h-10 rounded-full bg-brand-50 border border-brand-100 flex items-center justify-center text-sm font-bold text-brand-700">
            {u.name?.charAt(0)?.toUpperCase() || '?'}
          </div>
          <span
            className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-white ${statusCfg.dot}`}
            title={`${statusCfg.label}: ${statusCfg.desc}`}
          />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-sm font-semibold text-gray-900 group-hover:text-brand-700 transition-colors truncate">
              {u.name}
            </span>
            {u.is_admin && (
              <span className="text-[10px] font-medium bg-amber-100 text-amber-800 px-1.5 py-0.2 rounded border border-amber-200">
                Admin
              </span>
            )}
            <span
              className={`text-[10px] font-medium px-1.5 py-0.2 rounded ${
                u.plan === 'pro' ? 'bg-emerald-100 text-emerald-800 border border-emerald-200' : 'bg-gray-100 text-gray-600'
              }`}
            >
              {u.plan === 'pro' ? 'Pro' : 'Basic'}
            </span>
            <span className={`text-[10px] font-medium px-1.5 py-0.2 rounded border ${statusCfg.bg}`}>
              {statusCfg.label}
            </span>
            {u.auth_provider === 'google' && (
              <span className="text-[10px] font-medium px-1.5 py-0.2 rounded bg-blue-50 text-blue-700 border border-blue-200">
                Google
              </span>
            )}
            {u.telegram_id && (
              <span className="text-[10px] font-medium px-1.5 py-0.2 rounded bg-sky-50 text-sky-700 border border-sky-200">
                📱 TG
              </span>
            )}
          </div>

          <p className="text-xs text-gray-500 truncate mt-0.5">
            {u.email || <span className="text-gray-400 italic">Tanpa email (TG-only)</span>}
          </p>

          <div className="flex items-center gap-2 mt-1.5 text-[11px] text-gray-500 flex-wrap">
            <span className="inline-flex items-center gap-1 bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">
              📁 <b className="text-gray-700">{u.envelopes_count || 0}</b> amplop
            </span>
            <span className="inline-flex items-center gap-1 bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">
              📝 <b className="text-gray-700">{u.txn_count || 0}</b> txn
            </span>
            <span className="inline-flex items-center gap-1 bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">
              💰 Bulan ini: <b className="text-gray-700">{formatShort(u.month_spent || 0)}</b>
            </span>
            <span className="inline-flex items-center gap-1 text-gray-500">
              ⏱️ {lastActiveStr ? `Aktif ${lastActiveStr}` : 'Belum pernah catat'}
            </span>
            <span className="text-gray-300">·</span>
            <span className="text-gray-400">
              Daftar {formatDate(u.created_at)}
            </span>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-1 shrink-0 self-end sm:self-center" onClick={e => e.stopPropagation()}>
        <button
          onClick={handleDmClick}
          title="Kirim Direct Message ke user ini"
          className="text-xs px-2.5 py-1 bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100 font-medium"
        >
          ✉️ DM
        </button>
        {u.plan !== 'pro' ? (
          <button
            onClick={(e) => doAction(e, 'upgrade')}
            disabled={loading}
            title="Upgrade ke Pro"
            className="text-xs px-2.5 py-1 bg-brand-50 text-brand-600 rounded-lg hover:bg-brand-100 font-medium disabled:opacity-50"
          >
            ⬆ Pro
          </button>
        ) : (
          <button
            onClick={(e) => doAction(e, 'downgrade')}
            disabled={loading}
            title="Downgrade ke Basic"
            className="text-xs px-2.5 py-1 bg-gray-50 text-gray-500 rounded-lg hover:bg-gray-100 font-medium disabled:opacity-50"
          >
            ⬇ Basic
          </button>
        )}
        {!u.is_admin ? (
          <button
            onClick={(e) => doAction(e, 'make_admin')}
            disabled={loading}
            title="Jadikan Admin"
            className="text-xs px-2 py-1 bg-amber-50 text-amber-600 rounded-lg hover:bg-amber-100 disabled:opacity-50"
          >
            👑
          </button>
        ) : (
          <button
            onClick={(e) => doAction(e, 'remove_admin')}
            disabled={loading}
            title="Hapus Hak Admin"
            className="text-xs px-2 py-1 bg-gray-50 text-gray-400 rounded-lg hover:bg-gray-100 disabled:opacity-50"
          >
            👤
          </button>
        )}
        <button
          onClick={(e) => doAction(e, 'ban')}
          disabled={loading}
          title="Ban User"
          className="text-xs px-2 py-1 bg-red-50 text-red-500 rounded-lg hover:bg-red-100 disabled:opacity-50"
        >
          🚫
        </button>
        <button
          onClick={() => onSelectUser(u.id)}
          className="text-xs px-2.5 py-1 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium ml-1"
        >
          Detail →
        </button>
      </div>
    </div>
  );
}

function UserDetailModal({ userId, onClose, onAction, onQuickDm }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionLoading, setActionLoading] = useState(false);
  const [copiedId, setCopiedId] = useState(false);

  useEffect(() => {
    let isMounted = true;
    const fetchDetail = async () => {
      setLoading(true);
      setError('');
      const res = await api.request(`/admin/users/${userId}/detail`);
      if (res.ok) {
        const d = await res.json();
        if (isMounted) setData(d);
      } else {
        if (isMounted) setError('Gagal memuat detail user');
      }
      if (isMounted) setLoading(false);
    };
    fetchDetail();
    return () => { isMounted = false; };
  }, [userId]);

  const doAction = async (action) => {
    if (action === 'ban' && !confirm(`Ban ${data?.user?.name}?`)) return;
    setActionLoading(true);
    await onAction(userId, action);
    const res = await api.request(`/admin/users/${userId}/detail`);
    if (res.ok) setData(await res.json());
    setActionLoading(false);
  };

  const copyUserId = () => {
    if (navigator?.clipboard && userId) {
      navigator.clipboard.writeText(userId);
      setCopiedId(true);
      setTimeout(() => setCopiedId(false), 2000);
    }
  };

  if (!userId) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/40 backdrop-blur-xs overflow-y-auto">
      <div className="bg-white rounded-2xl max-w-2xl w-full shadow-2xl border border-gray-100 max-h-[92vh] flex flex-col overflow-hidden my-auto">
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-gray-100 flex items-center justify-between bg-gray-50/60 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-11 h-11 rounded-full bg-brand-100 text-brand-700 font-bold flex items-center justify-center text-base shrink-0">
              {data?.user?.name?.charAt(0)?.toUpperCase() || '?'}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-bold text-base text-gray-900 truncate">{data?.user?.name || 'Memuat...'}</h3>
                {data?.user?.plan === 'pro' ? (
                  <span className="text-xs px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-medium">Pro</span>
                ) : (
                  <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600 font-medium">Basic</span>
                )}
                {data?.user?.is_admin && (
                  <span className="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-800 font-medium">Admin</span>
                )}
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-500 mt-0.5">
                <span className="truncate">{data?.user?.email || 'Tanpa email (TG-only)'}</span>
                <span>·</span>
                <button
                  onClick={copyUserId}
                  className="font-mono text-gray-400 hover:text-gray-700 cursor-pointer flex items-center gap-1"
                  title="Salin User ID"
                >
                  ID: {userId.slice(0, 8)}... {copiedId ? '✓ disalin' : '📋'}
                </button>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-gray-100 hover:bg-gray-200 text-gray-500 flex items-center justify-center text-sm transition-colors shrink-0"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="p-4 sm:p-5 overflow-y-auto space-y-4">
          {loading ? (
            <div className="py-16 text-center text-gray-400 text-sm">
              <div className="inline-block w-6 h-6 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mb-2" />
              <p>Memuat detail user...</p>
            </div>
          ) : error ? (
            <div className="p-4 bg-red-50 text-red-600 rounded-xl text-sm text-center">{error}</div>
          ) : (
            <>
              {/* Status Banner */}
              {(() => {
                const statusCfg = STATUS_CONFIG[data.user.status] || STATUS_CONFIG.dormant;
                return (
                  <div className={`p-3 rounded-xl border flex items-center justify-between ${statusCfg.bg}`}>
                    <div className="flex items-center gap-2">
                      <span className={`w-2.5 h-2.5 rounded-full ${statusCfg.dot}`} />
                      <span className="font-semibold text-xs sm:text-sm">Status: {statusCfg.label}</span>
                    </div>
                    <span className="text-xs opacity-80">{statusCfg.desc}</span>
                  </div>
                );
              })()}

              {/* KPI Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                <div className="p-3 bg-gray-50 rounded-xl border border-gray-100">
                  <p className="text-[11px] text-gray-500">Total Transaksi</p>
                  <p className="font-bold text-lg text-gray-900 mt-0.5">{data.stats.txn_count}</p>
                  <p className="text-[10px] text-gray-400 mt-0.5 truncate">
                    {data.stats.last_txn_at ? `Terakhir: ${timeAgo(data.stats.last_txn_at)}` : 'Belum pernah'}
                  </p>
                </div>
                <div className="p-3 bg-gray-50 rounded-xl border border-gray-100">
                  <p className="text-[11px] text-gray-500">Amplop Aktif</p>
                  <p className="font-bold text-lg text-gray-900 mt-0.5">{data.stats.envelopes_count}</p>
                  <p className="text-[10px] text-gray-400 mt-0.5 truncate">di {data.household?.name || 'Rumah'}</p>
                </div>
                <div className="p-3 bg-gray-50 rounded-xl border border-gray-100">
                  <p className="text-[11px] text-gray-500">Belanja Bulan Ini</p>
                  <p className="font-bold text-lg text-brand-700 mt-0.5">{formatCurrency(data.stats.month_spent)}</p>
                  <p className="text-[10px] text-gray-400 mt-0.5 truncate">All-time: {formatShort(data.stats.total_spent)}</p>
                </div>
                <div className="p-3 bg-gray-50 rounded-xl border border-gray-100">
                  <p className="text-[11px] text-gray-500">Auth & Koneksi</p>
                  <p className="font-bold text-sm text-gray-900 mt-1 capitalize">
                    {data.user.auth_provider === 'google' ? '🌐 Google' : data.user.auth_provider === 'telegram' ? '📱 Telegram' : '✉️ Email'}
                  </p>
                  <p className="text-[10px] text-gray-400 mt-0.5 truncate">
                    {data.user.telegram_id ? `📱 TG linked` : 'Belum link TG'}
                  </p>
                </div>
              </div>

              {/* Account Meta List */}
              <div className="bg-gray-50/70 p-3.5 rounded-xl border border-gray-100 space-y-2 text-xs">
                <h4 className="font-semibold text-gray-700 mb-2">Informasi Akun & Pengaturan</h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 text-gray-600">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Tanggal Daftar:</span>
                    <span className="font-medium text-gray-800">{formatDate(data.user.created_at)} ({timeAgo(data.user.created_at)})</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Terakhir Login:</span>
                    <span className="font-medium text-gray-800">
                      {data.user.last_login ? `${formatDate(data.user.last_login)} (${timeAgo(data.user.last_login)})` : 'Belum pernah login webapp'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Tipe Penghasilan:</span>
                    <span className="font-medium text-gray-800 capitalize">{data.user.income_type || 'Monthly'} (Payday: Tgl {data.user.payday_day || 1})</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Timezone:</span>
                    <span className="font-medium text-gray-800">{data.user.timezone || 'Asia/Jakarta'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Household:</span>
                    <span className="font-medium text-gray-800">
                      {data.household ? `${data.household.name} (${data.household.role}, ${data.household.members_count} anggota)` : '-'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Telegram ID:</span>
                    <span className="font-medium text-gray-800">{data.user.telegram_id || '-'}</span>
                  </div>
                </div>
              </div>

              {/* Amplop List */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="font-semibold text-xs sm:text-sm text-gray-900 flex items-center gap-1.5">
                    📁 Amplop Aktif ({data.envelopes?.length || 0})
                  </h4>
                  {data.envelopes?.length > 0 && (
                    <span className="text-xs text-gray-400">
                      Total Budget: {formatCurrency(data.envelopes.reduce((sum, e) => sum + (e.budget_amount || 0), 0))}
                    </span>
                  )}
                </div>
                {data.envelopes?.length === 0 ? (
                  <p className="text-xs text-gray-400 italic bg-gray-50 p-3 rounded-lg border border-dashed border-gray-200 text-center">
                    Belum memiliki amplop
                  </p>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-48 overflow-y-auto p-0.5">
                    {data.envelopes.map(env => (
                      <div key={env.id} className="p-2.5 rounded-lg border border-gray-100 bg-white flex items-center justify-between text-xs shadow-2xs">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-base shrink-0">{env.emoji || '📦'}</span>
                          <div className="min-w-0">
                            <p className="font-medium text-gray-900 truncate">{env.name}</p>
                            <div className="flex items-center gap-1 text-[10px] text-gray-400 mt-0.5">
                              <span className="capitalize">{env.purpose?.replace('_', ' ')}</span>
                              {env.classification && (
                                <>
                                  <span>·</span>
                                  <span className="capitalize font-medium text-gray-600">{env.classification}</span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>
                        <span className="font-semibold text-gray-700 shrink-0 ml-2">
                          {formatShort(env.budget_amount)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Recent Transactions List */}
              <div>
                <h4 className="font-semibold text-xs sm:text-sm text-gray-900 mb-2 flex items-center gap-1.5">
                  📝 Transaksi Terakhir ({data.recent_transactions?.length || 0})
                </h4>
                {data.recent_transactions?.length === 0 ? (
                  <p className="text-xs text-gray-400 italic bg-gray-50 p-3 rounded-lg border border-dashed border-gray-200 text-center">
                    Belum pernah mencatat transaksi
                  </p>
                ) : (
                  <div className="divide-y divide-gray-100 border border-gray-100 rounded-xl overflow-hidden bg-white max-h-56 overflow-y-auto">
                    {data.recent_transactions.map(txn => (
                      <div key={txn.id} className="p-2.5 flex items-center justify-between text-xs hover:bg-gray-50">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <span className="text-sm shrink-0">{txn.envelope_emoji || '📝'}</span>
                          <div className="min-w-0">
                            <p className="font-medium text-gray-900 truncate">
                              {txn.description || txn.envelope_name}
                            </p>
                            <p className="text-[10px] text-gray-400">
                              {txn.transaction_date} · {txn.envelope_name} · via {txn.source}
                              {txn.is_balance_check && ' · ⚖️ cocokkan saldo'}
                            </p>
                          </div>
                        </div>
                        <span className="font-bold text-gray-900 shrink-0 ml-2">
                          {formatCurrency(txn.amount)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Footer Actions */}
        <div className="p-3.5 sm:p-4 border-t border-gray-100 bg-gray-50/60 flex flex-wrap items-center justify-between gap-2 shrink-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <button
              onClick={() => {
                onClose();
                onQuickDm(userId);
              }}
              className="text-xs px-3 py-1.5 bg-blue-50 text-blue-700 rounded-lg font-medium hover:bg-blue-100 transition-colors"
            >
              ✉️ Kirim DM
            </button>
            {data?.user?.plan !== 'pro' ? (
              <button
                onClick={() => doAction('upgrade')}
                disabled={actionLoading}
                className="text-xs px-3 py-1.5 bg-emerald-50 text-emerald-700 rounded-lg font-medium hover:bg-emerald-100 disabled:opacity-50"
              >
                ⬆ Upgrade ke Pro
              </button>
            ) : (
              <button
                onClick={() => doAction('downgrade')}
                disabled={actionLoading}
                className="text-xs px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg font-medium hover:bg-gray-200 disabled:opacity-50"
              >
                ⬇ Downgrade ke Basic
              </button>
            )}
            {!data?.user?.is_admin ? (
              <button
                onClick={() => doAction('make_admin')}
                disabled={actionLoading}
                className="text-xs px-3 py-1.5 bg-amber-50 text-amber-700 rounded-lg font-medium hover:bg-amber-100 disabled:opacity-50"
              >
                👑 Jadikan Admin
              </button>
            ) : (
              <button
                onClick={() => doAction('remove_admin')}
                disabled={actionLoading}
                className="text-xs px-3 py-1.5 bg-gray-100 text-gray-500 rounded-lg font-medium hover:bg-gray-200 disabled:opacity-50"
              >
                👤 Hapus Admin
              </button>
            )}
            <button
              onClick={() => doAction('ban')}
              disabled={actionLoading}
              className="text-xs px-3 py-1.5 bg-red-50 text-red-600 rounded-lg font-medium hover:bg-red-100 disabled:opacity-50"
            >
              🚫 Ban User
            </button>
          </div>
          <button
            onClick={onClose}
            className="text-xs px-4 py-1.5 bg-gray-200 text-gray-700 rounded-lg font-medium hover:bg-gray-300 ml-auto"
          >
            Tutup
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Admin() {
  const [dash, setDash] = useState(null);
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState('');
  const [userFilter, setUserFilter] = useState('all');
  const [userSort, setUserSort] = useState('newest');
  const [selectedUserId, setSelectedUserId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('dashboard');
  const [notifTitle, setNotifTitle] = useState('');
  const [notifMsg, setNotifMsg] = useState('');
  const [notifSendTg, setNotifSendTg] = useState(false);
  const [notifTgText, setNotifTgText] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [dmUserId, setDmUserId] = useState('');
  const [dmSubject, setDmSubject] = useState('');
  const [dmBody, setDmBody] = useState('');
  const [dmCtaText, setDmCtaText] = useState('');
  const [dmCtaUrl, setDmCtaUrl] = useState('');
  const [dmSendTg, setDmSendTg] = useState(false);
  const [dmTgText, setDmTgText] = useState('');
  const [dmSending, setDmSending] = useState(false);
  const [articles, setArticles] = useState([]);

  const handleQuickDm = (userId) => {
    setDmUserId(userId);
    setTab('tools');
    setTimeout(() => {
      const dmEl = document.getElementById('dm-section');
      if (dmEl) dmEl.scrollIntoView({ behavior: 'smooth' });
    }, 100);
  };

  const ARTICLES = [
    { title: "AI Advisor Jatahku — Asisten Keuangan Pintar di Dashboard Kamu", slug: "ai-advisor-pintar", description: "AI Advisor menganalisis pola belanja, progres tabungan, dan deadline sinking fund untuk memberikan insight personal.", url: "https://blog.jatahku.com/insight/ai-advisor-pintar/" },
    { title: "FAB Speed Dial — 4 Inputan Cepat dalam Satu Tombol", slug: "fab-speed-dial-4-inputan", description: "Tombol + melayang sekarang bisa mencatat pengeluaran, buat amplop baru, tambah income, dan tambah langganan — semuanya tanpa pindah halaman.", url: "https://blog.jatahku.com/insight/fab-speed-dial-4-inputan/" },
    { title: "Group & Purpose Amplop — Organisasi Keuangan yang Lebih Rapi", slug: "group-purpose-amplop", description: "Amplop sekarang punya purpose (expense/saving/sinking_fund) dan group. Setiap tipe punya perilaku berbeda.", url: "https://blog.jatahku.com/insight/group-purpose-amplop/" },
    { title: "Memahami Budget Amount — Rencana vs Realisasi di Jatahku", slug: "memahami-budget-amount", description: "Apa itu budget_amount? Kenapa penting? Bagaimana bedanya dengan allocated? Tutorial lengkap memahami konsep budget di envelope budgeting.", url: "https://blog.jatahku.com/insight/memahami-budget-amount/" },
  ];

  const loadDash = async () => {
    const res = await api.request('/admin/dashboard');
    if (res.ok) setDash(await res.json());
    else setError('Admin access required');
    setLoading(false);
  };

  const loadUsers = async (q) => {
    const url = q ? `/admin/users?search=${encodeURIComponent(q)}` : '/admin/users';
    const res = await api.request(url);
    if (res.ok) setUsers(await res.json());
  };

  useEffect(() => { loadDash(); loadUsers(); }, []);

  const handleUserAction = async (userId, action) => {
    const res = await api.request(`/admin/users/${userId}/action`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    });
    if (res.ok) {
      const d = await res.json();
      setActionMsg(`✅ ${d.action}: ${d.user}`);
      setTimeout(() => setActionMsg(''), 3000);
      loadUsers(search);
      loadDash();
    }
  };

  const handleSearch = (val) => {
    setSearch(val);
    loadUsers(val);
  };

  const upgradeAll = async () => {
    if (!confirm('Upgrade semua user ke Pro?')) return;
    const res = await api.request('/admin/users/upgrade-all', { method: 'POST' });
    if (res.ok) {
      const d = await res.json();
      setActionMsg(`✅ ${d.total_pro} users sekarang Pro`);
      setTimeout(() => setActionMsg(''), 3000);
      loadUsers(search);
      loadDash();
    }
  };

  const batchUpgrade = async () => {
    const n = prompt('Berapa user random yang mau di-upgrade?', '5');
    if (!n) return;
    const res = await api.request(`/admin/users/batch-upgrade?count=${n}`, { method: 'POST' });
    if (res.ok) {
      const d = await res.json();
      setActionMsg(`✅ Upgraded: ${d.upgraded.join(', ')}`);
      setTimeout(() => setActionMsg(''), 5000);
      loadUsers(search);
      loadDash();
    }
  };

  const sendNotifAll = async () => {
    if (!notifTitle || !notifMsg) return;
    let url = `/admin/notify-all?title=${encodeURIComponent(notifTitle)}&message=${encodeURIComponent(notifMsg)}&send_telegram=${notifSendTg}`;
    if (notifSendTg && notifTgText) url += `&telegram_text=${encodeURIComponent(notifTgText)}`;
    const res = await api.request(url, { method: 'POST' });
    if (res.ok) {
      const d = await res.json();
      const tgInfo = notifSendTg ? `, TG: ${d.tg_sent} terkirim${d.tg_failed ? `, ${d.tg_failed} gagal` : ''}` : '';
      setActionMsg(`✅ Notifikasi terkirim ke ${d.sent} user${tgInfo}`);
      setNotifTitle(''); setNotifMsg(''); setNotifSendTg(false); setNotifTgText('');
      setTimeout(() => setActionMsg(''), 5000);
    }
  };

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;
  if (error) return <div className="text-center py-12 text-red-400">{error}</div>;
  if (!dash) return null;

  const d = dash;
  const signups = d.charts.signups.map(s => ({ ...s, date: s.date.slice(5) }));
  const txns = d.charts.daily_txns.map(t => ({ ...t, date: t.date.slice(5) }));

  const userCounts = {
    all: users.length,
    active: users.filter(u => u.status === 'active').length,
    idle: users.filter(u => u.status === 'idle').length,
    no_txn: users.filter(u => u.status === 'no_txn').length,
    dormant: users.filter(u => u.status === 'dormant').length,
    pro: users.filter(u => u.plan === 'pro').length,
    basic: users.filter(u => u.plan !== 'pro').length,
    tg: users.filter(u => Boolean(u.telegram_id)).length,
  };

  const filteredUsers = users.filter(u => {
    if (userFilter === 'active') return u.status === 'active';
    if (userFilter === 'idle') return u.status === 'idle';
    if (userFilter === 'no_txn') return u.status === 'no_txn';
    if (userFilter === 'dormant') return u.status === 'dormant';
    if (userFilter === 'pro') return u.plan === 'pro';
    if (userFilter === 'basic') return u.plan !== 'pro';
    if (userFilter === 'tg') return Boolean(u.telegram_id);
    return true;
  }).sort((a, b) => {
    if (userSort === 'newest') return new Date(b.created_at || 0) - new Date(a.created_at || 0);
    if (userSort === 'oldest') return new Date(a.created_at || 0) - new Date(b.created_at || 0);
    if (userSort === 'last_active') {
      const aTime = a.last_txn_at ? new Date(a.last_txn_at).getTime() : 0;
      const bTime = b.last_txn_at ? new Date(b.last_txn_at).getTime() : 0;
      return bTime - aTime;
    }
    if (userSort === 'most_txns') return (b.txn_count || 0) - (a.txn_count || 0);
    if (userSort === 'most_spent') return (b.month_spent || 0) - (a.month_spent || 0);
    return 0;
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-display font-bold">Admin</h1>
        <div className="flex gap-2">
          <button onClick={() => setTab('dashboard')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium ${tab === 'dashboard' ? 'bg-brand-50 text-brand-600' : 'text-gray-400'}`}>Dashboard</button>
          <button onClick={() => setTab('users')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium ${tab === 'users' ? 'bg-brand-50 text-brand-600' : 'text-gray-400'}`}>Users</button>
          <button onClick={() => setTab('tools')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium ${tab === 'tools' ? 'bg-brand-50 text-brand-600' : 'text-gray-400'}`}>Tools</button>
          <button onClick={() => setTab('payments')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium ${tab === 'payments' ? 'bg-brand-50 text-brand-600' : 'text-gray-400'}`}>Payments</button>
        </div>
      </div>

      {actionMsg && <div className="bg-green-50 border border-green-200 text-sm px-4 py-3 rounded-xl text-green-700">{actionMsg}</div>}

      {tab === 'dashboard' && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KPI label="Total Users" value={d.users.total} sub={`+${d.users.this_week} minggu ini`} color="text-brand-600" />
            <KPI label="Pro Users" value={d.users.pro} sub={`${d.users.basic} basic`} color="text-amber-500" />
            <KPI label="TG Linked" value={d.users.tg_linked} sub={`${Math.round(d.users.tg_linked/d.users.total*100)}% adoption`} color="text-blue-500" />
            <KPI label="Total Transaksi" value={d.transactions.total} sub={`${d.transactions.today} hari ini`} />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <KPI label="Spending hari ini" value={d.transactions.today_amount} />
            <KPI label="Spending bulan ini" value={d.transactions.month_amount} />
            <KPI label="Total dikelola" value={d.transactions.total_managed} color="text-brand-600" />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="card">
              <h3 className="font-semibold text-sm mb-3">Signups (14 hari)</h3>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={signups}>
                  <XAxis dataKey="date" tick={{fontSize: 10}} tickLine={false} axisLine={false} />
                  <YAxis tick={{fontSize: 10}} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="count" name="Signups" fill="#0F6E56" radius={[3,3,0,0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="card">
              <h3 className="font-semibold text-sm mb-3">Transaksi (14 hari)</h3>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={txns}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                  <XAxis dataKey="date" tick={{fontSize: 10}} tickLine={false} axisLine={false} />
                  <YAxis tick={{fontSize: 10}} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip content={<CustomTooltip />} />
                  <Area type="monotone" dataKey="count" name="Transaksi" stroke="#BA7517" fill="#BA7517" fillOpacity={0.15} strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}

      {tab === 'users' && (
        <div className="space-y-3">
          {/* Filter Chips */}
          <div className="flex gap-1.5 overflow-x-auto pb-1 text-xs no-scrollbar">
            {[
              { id: 'all', label: 'Semua', count: userCounts.all },
              { id: 'active', label: '🟢 Aktif', count: userCounts.active },
              { id: 'idle', label: '🟡 Jarang', count: userCounts.idle },
              { id: 'no_txn', label: '⚪ Belum Catat', count: userCounts.no_txn },
              { id: 'dormant', label: '🔴 Dormant', count: userCounts.dormant },
              { id: 'pro', label: 'Pro', count: userCounts.pro },
              { id: 'basic', label: 'Basic', count: userCounts.basic },
              { id: 'tg', label: '📱 Telegram', count: userCounts.tg },
            ].map(f => (
              <button
                key={f.id}
                onClick={() => setUserFilter(f.id)}
                className={`px-3 py-1.5 rounded-xl font-medium whitespace-nowrap transition-colors flex items-center gap-1.5 ${
                  userFilter === f.id
                    ? 'bg-brand-600 text-white shadow-2xs'
                    : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                <span>{f.label}</span>
                <span className={`text-[10px] px-1.5 py-0.2 rounded-full ${userFilter === f.id ? 'bg-brand-700/60 text-white' : 'bg-gray-100 text-gray-700'}`}>
                  {f.count}
                </span>
              </button>
            ))}
          </div>

          {/* Search bar & Sort controls */}
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              className="input text-sm flex-1"
              placeholder="Cari nama atau email..."
              value={search}
              onChange={e => handleSearch(e.target.value)}
            />
            <div className="flex items-center gap-2">
              <select
                className="input text-xs py-2 w-auto"
                value={userSort}
                onChange={e => setUserSort(e.target.value)}
              >
                <option value="newest">📅 Terbaru Daftar</option>
                <option value="oldest">📅 Terlama Daftar</option>
                <option value="last_active">⏱️ Terakhir Transaksi</option>
                <option value="most_txns">📝 Transaksi Terbanyak</option>
                <option value="most_spent">💰 Belanja Terbanyak (Bulan Ini)</option>
              </select>
              <span className="text-xs text-gray-400 whitespace-nowrap">
                {filteredUsers.length} user
              </span>
            </div>
          </div>

          {/* User List Card */}
          <div className="card divide-y divide-gray-50 p-2 sm:p-3">
            {filteredUsers.map(u => (
              <UserRow
                key={u.id}
                u={u}
                onAction={handleUserAction}
                onSelectUser={setSelectedUserId}
                onQuickDm={handleQuickDm}
              />
            ))}
            {filteredUsers.length === 0 && (
              <p className="text-center text-gray-400 py-10 text-sm">
                Tidak ada user ditemukan untuk filter ini
              </p>
            )}
          </div>
        </div>
      )}


      {tab === 'tools' && (
        <div className="space-y-4">
          <div className="card">
            <h3 className="font-semibold text-sm mb-3">🎁 Promo Tools</h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Upgrade semua user ke Pro</p>
                  <p className="text-xs text-gray-400">First 100 promo — semua user aktif jadi Pro</p>
                </div>
                <button onClick={upgradeAll} className="text-sm px-3 py-1.5 bg-brand-50 text-brand-600 rounded-lg hover:bg-brand-100">Upgrade All</button>
              </div>
              <div className="flex items-center justify-between border-t border-gray-50 pt-3">
                <div>
                  <p className="text-sm font-medium">Random upgrade</p>
                  <p className="text-xs text-gray-400">Pilih N user basic random → Pro</p>
                </div>
                <button onClick={batchUpgrade} className="text-sm px-3 py-1.5 bg-amber-50 text-amber-600 rounded-lg hover:bg-amber-100">Random Upgrade</button>
              </div>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-sm mb-3">📱 Telegram Reminder</h3>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Email reminder ke user tanpa Telegram</p>
                <p className="text-xs text-gray-400">Kirim email ajakan link Telegram ke semua user yang belum connect</p>
              </div>
              <button onClick={async () => {
                if (!confirm('Kirim email reminder ke semua user tanpa Telegram?')) return;
                const res = await api.request('/admin/send-tg-reminders', { method: 'POST' });
                if (res.ok) { const d = await res.json(); setActionMsg(`✅ Email terkirim ke ${d.sent} dari ${d.total_unlinked} user`); setTimeout(() => setActionMsg(''), 5000); }
              }} className="text-sm px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100">
                Kirim Reminder
              </button>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-sm mb-3">📢 Broadcast Notification</h3>
            <div className="space-y-2">
              <input className="input text-sm" placeholder="Judul notifikasi" value={notifTitle} onChange={e => setNotifTitle(e.target.value)} />
              <textarea className="input text-sm" rows="3" placeholder="Isi pesan (in-app notification)..." value={notifMsg} onChange={e => setNotifMsg(e.target.value)} />
              <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none pt-1">
                <input type="checkbox" checked={notifSendTg} onChange={e => setNotifSendTg(e.target.checked)} className="rounded" />
                Kirim juga ke Telegram (hanya user yang sudah connect)
              </label>
              {notifSendTg && (
                <textarea className="input text-sm font-mono" rows="3"
                  placeholder="Pesan Telegram (Markdown). Kosongkan = gunakan judul + isi di atas."
                  value={notifTgText} onChange={e => setNotifTgText(e.target.value)} />
              )}
              <button onClick={sendNotifAll} disabled={!notifTitle || !notifMsg}
                className="btn-primary text-sm py-2 disabled:opacity-50">
                {notifSendTg ? 'Kirim ke semua user + Telegram' : 'Kirim ke semua user'}
              </button>
            </div>
          </div>

          <div id="dm-section" className="card">
            <h3 className="font-semibold text-sm mb-3">✉️ Direct Message ke User</h3>
            <div className="space-y-2">
              <select className="input text-sm" value={dmUserId} onChange={e => setDmUserId(e.target.value)}>
                <option value="">Pilih user penerima...</option>
                {users.filter(u => u.email && !u.email.startsWith('deleted_') && !u.email.startsWith('banned_')).map(u => (
                  <option key={u.id} value={u.id}>{u.name} — {u.email}</option>
                ))}
              </select>
              <input className="input text-sm" placeholder="Subject email" value={dmSubject} onChange={e => setDmSubject(e.target.value)} />
              <textarea className="input text-sm font-mono" rows="5" placeholder="Isi pesan (HTML diperbolehkan, misal: <p>teks</p><br><b>bold</b>)" value={dmBody} onChange={e => setDmBody(e.target.value)} />
              <div className="grid grid-cols-2 gap-2">
                <input className="input text-sm" placeholder="Teks tombol email (opsional)" value={dmCtaText} onChange={e => setDmCtaText(e.target.value)} />
                <input className="input text-sm" placeholder="URL tombol email (opsional)" value={dmCtaUrl} onChange={e => setDmCtaUrl(e.target.value)} />
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none pt-1">
                <input type="checkbox" checked={dmSendTg} onChange={e => setDmSendTg(e.target.checked)} className="rounded" />
                Kirim juga ke Telegram (jika user sudah connect)
              </label>
              {dmSendTg && (
                <textarea className="input text-sm font-mono" rows="3"
                  placeholder="Pesan Telegram (Markdown: *bold*, _italic_). Kosongkan untuk hanya kirim subject sebagai judul."
                  value={dmTgText} onChange={e => setDmTgText(e.target.value)} />
              )}
              <button disabled={!dmUserId || !dmSubject || !dmBody || dmSending}
                onClick={async () => {
                  const selectedUser = users.find(u => u.id === dmUserId);
                  const hasTg = selectedUser?.telegram_id;
                  const channels = ['email', ...(dmSendTg ? [hasTg ? 'Telegram' : 'Telegram (tidak tersambung, akan dilewati)'] : [])].join(' + ');
                  if (!confirm(`Kirim ke ${selectedUser?.name} via ${channels}?`)) return;
                  setDmSending(true);
                  const res = await api.request('/admin/send-email-user', {
                    method: 'POST',
                    body: JSON.stringify({ user_id: dmUserId, subject: dmSubject, body: dmBody, cta_text: dmCtaText || null, cta_url: dmCtaUrl || null, send_telegram: dmSendTg, telegram_text: dmTgText || null }),
                  });
                  setDmSending(false);
                  if (res.ok) {
                    const d = await res.json();
                    const r = d.results;
                    setActionMsg(`✅ ${d.name} — email: ${r.email}${r.telegram ? `, TG: ${r.telegram}` : ''}`);
                    setDmUserId(''); setDmSubject(''); setDmBody(''); setDmCtaText(''); setDmCtaUrl(''); setDmSendTg(false); setDmTgText('');
                    setTimeout(() => setActionMsg(''), 6000);
                  } else {
                    const d = await res.json();
                    setActionMsg(`❌ Gagal: ${d.detail}`);
                    setTimeout(() => setActionMsg(''), 5000);
                  }
                }}
                className="btn-primary text-sm py-2 disabled:opacity-50">
                {dmSending ? 'Mengirim...' : `Kirim${dmSendTg ? ' Email + Telegram' : ' Email'}`}
              </button>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-sm mb-3">📢 Broadcast Artikel ke Semua User</h3>
            <div className="space-y-2">
              <select className="input text-sm" value={dmSubject} onChange={e => {
                const selected = ARTICLES.find(a => a.title === e.target.value);
                if (selected) {
                  setDmSubject(selected.title);
                  setDmBody(`<p>${selected.description}</p><br><p><a href="${selected.url}" style="color:#0F6E56">Baca selengkapnya di blog →</a></p>`);
                  setDmCtaText('Baca Artikel');
                  setDmCtaUrl(selected.url);
                }
              }}>
                <option value="">Pilih artikel...</option>
                {ARTICLES.map(a => (
                  <option key={a.slug} value={a.title}>{a.title}</option>
                ))}
              </select>
              <p className="text-xs text-gray-400">Pilih artikel, edit subject/body kalau perlu, lalu broadcast.</p>
              <input className="input text-sm" placeholder="Subject email" value={dmSubject} onChange={e => setDmSubject(e.target.value)} />
              <textarea className="input text-sm font-mono" rows="4" placeholder="Isi email (HTML)" value={dmBody} onChange={e => setDmBody(e.target.value)} />
              <div className="grid grid-cols-2 gap-2">
                <input className="input text-sm" placeholder="Teks tombol (opsional)" value={dmCtaText} onChange={e => setDmCtaText(e.target.value)} />
                <input className="input text-sm" placeholder="URL tombol (opsional)" value={dmCtaUrl} onChange={e => setDmCtaUrl(e.target.value)} />
              </div>
              <button disabled={!dmSubject || !dmBody || dmSending}
                onClick={async () => {
                  if (!confirm(`Broadcast "${dmSubject}" ke SEMUA user via email?`)) return;
                  setDmSending(true);
                  const res = await api.request('/admin/broadcast-article', {
                    method: 'POST',
                    body: JSON.stringify({ subject: dmSubject, body: dmBody, cta_text: dmCtaText || null, cta_url: dmCtaUrl || null }),
                  });
                  setDmSending(false);
                  if (res.ok) {
                    const d = await res.json();
                    setActionMsg(`✅ Terkirim ke ${d.sent} user (${d.failed} gagal)`);
                    setTimeout(() => setActionMsg(''), 6000);
                  } else {
                    const d = await res.json();
                    setActionMsg(`❌ Gagal: ${d.detail}`);
                    setTimeout(() => setActionMsg(''), 5000);
                  }
                }}
                className="btn-primary text-sm py-2 disabled:opacity-50">
                {dmSending ? 'Mengirim...' : '📢 Broadcast ke Semua User'}
              </button>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-sm mb-3">🖥️ System Info</h3>
            <div className="space-y-1 text-sm text-gray-500">
              <p>API: <a href="https://api.jatahku.com/health" target="_blank" className="text-brand-600">api.jatahku.com/health</a></p>
              <p>GitHub: <a href="https://github.com/mtyatno/jatahku" target="_blank" className="text-brand-600">mtyatno/jatahku</a></p>
              <p>VPS: 2vCPU / 4GB RAM / Ubuntu 24.04</p>
              <p>Stack: FastAPI + PostgreSQL + Redis + React</p>
            </div>
          </div>
        </div>
      )}
      {tab === 'payments' && <PaymentsTab onAction={() => { setActionMsg('✅ Done'); setTimeout(() => setActionMsg(''), 3000); }} />}

      {selectedUserId && (
        <UserDetailModal
          userId={selectedUserId}
          onClose={() => setSelectedUserId(null)}
          onAction={handleUserAction}
          onQuickDm={handleQuickDm}
        />
      )}
    </div>
  );
}

function PaymentsTab({ onAction }) {
  const [orders, setOrders] = useState([]);
  const [promos, setPromos] = useState([]);
  const [banks, setBanks] = useState([]);
  const [filter, setFilter] = useState('');
  const [newBank, setNewBank] = useState({ bank: '', account_number: '', account_name: '' });
  const [newPromo, setNewPromo] = useState({ code: '', discount_pct: 0, is_free: false, max_uses: '', event_name: '', valid_days: '' });
  const [showAddBank, setShowAddBank] = useState(false);
  const [showAddPromo, setShowAddPromo] = useState(false);
  const [editingPromoId, setEditingPromoId] = useState(null);
  const [editPromo, setEditPromo] = useState({
    code: '',
    discount_pct: 0,
    is_free: false,
    max_uses: '',
    event_name: '',
    valid_days: '',
    clear_validity: false,
  });

  const load = async () => {
    const url = filter ? `/admin/payment-orders?status=${filter}` : '/admin/payment-orders';
    const r = await api.request(url);
    if (r.ok) setOrders(await r.json());
    const pr = await api.request('/admin/promo-codes');
    if (pr.ok) setPromos(await pr.json());
    const br = await api.request('/admin/settings/bank_accounts');
    if (br.ok) setBanks(br.value || []);
    try {
      const bData = await (await api.request('/admin/settings/bank_accounts')).json();
      setBanks(Array.isArray(bData.value) ? bData.value : JSON.parse(bData.value || '[]'));
    } catch { setBanks([]); }
  };

  useEffect(() => { load(); }, [filter]);

  const approveOrder = async (id) => {
    await api.request(`/admin/payment-orders/${id}/approve`, { method: 'POST' });
    onAction(); load();
  };

  const rejectOrder = async (id) => {
    const reason = prompt('Alasan penolakan:');
    if (!reason) return;
    await api.request(`/admin/payment-orders/${id}/reject?reason=${encodeURIComponent(reason)}`, { method: 'POST' });
    onAction(); load();
  };

  const saveBanks = async (list) => {
    await api.request(`/admin/settings/bank_accounts?value=${encodeURIComponent(JSON.stringify(list))}`, { method: 'PUT' });
    setBanks(list); onAction();
  };

  const addBank = () => {
    if (!newBank.bank || !newBank.account_number) return;
    saveBanks([...banks, newBank]);
    setNewBank({ bank: '', account_number: '', account_name: '' });
    setShowAddBank(false);
  };

  const removeBank = (idx) => saveBanks(banks.filter((_, i) => i !== idx));

  const createPromo = async () => {
    try {
      const r = await api.request('/admin/promo-codes', {
        method: 'POST',
        body: JSON.stringify({
          ...newPromo,
          max_uses: newPromo.max_uses ? parseInt(newPromo.max_uses) : null,
          valid_days: newPromo.valid_days ? parseInt(newPromo.valid_days) : null,
        }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        alert('Gagal buat promo: ' + (err.detail || r.status));
        return;
      }
      setNewPromo({ code: '', discount_pct: 0, is_free: false, max_uses: '', event_name: '', valid_days: '' });
      setShowAddPromo(false);
      onAction(); load();
    } catch (e) {
      alert('Gagal buat promo: ' + e.message);
    }
  };

  const startEditPromo = (p) => {
    setEditingPromoId(p.id);
    setEditPromo({
      code: p.code,
      discount_pct: p.discount_pct || 0,
      is_free: p.is_free || false,
      max_uses: p.max_uses ?? '',
      event_name: p.event_name || '',
      valid_days: '',
      clear_validity: false,
    });
  };

  const cancelEditPromo = () => {
    setEditingPromoId(null);
  };

  const saveEditPromo = async (id) => {
    try {
      const payload = {
        code: editPromo.code.trim().toUpperCase(),
        is_free: editPromo.is_free,
        discount_pct: editPromo.is_free ? 100 : (parseInt(editPromo.discount_pct) || 0),
        max_uses: editPromo.max_uses !== '' ? parseInt(editPromo.max_uses) : 0,
        event_name: editPromo.event_name.trim(),
      };
      if (editPromo.clear_validity) {
        payload.valid_days = 0;
      } else if (editPromo.valid_days !== '') {
        payload.valid_days = parseInt(editPromo.valid_days) || 0;
      }

      const r = await api.request(`/admin/promo-codes/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        alert('Gagal update promo: ' + (err.detail || r.status));
        return;
      }
      setEditingPromoId(null);
      onAction();
      load();
    } catch (e) {
      alert('Gagal update promo: ' + e.message);
    }
  };

  const togglePromoActive = async (p) => {
    const actionLabel = p.is_active ? 'Nonaktifkan' : 'Aktifkan';
    if (!confirm(`${actionLabel} promo ${p.code}?`)) return;
    try {
      const r = await api.request(`/admin/promo-codes/${p.id}/toggle-active`, { method: 'POST' });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        alert(`Gagal ${actionLabel.toLowerCase()} promo: ` + (err.detail || r.status));
        return;
      }
      onAction();
      load();
    } catch (e) {
      alert(`Gagal ${actionLabel.toLowerCase()} promo: ` + e.message);
    }
  };

  return (
    <div className="space-y-4">
      {/* Bank Accounts */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">🏦 Rekening Tujuan</h3>
        {banks.map((b, i) => (
          <div key={i} className="flex items-center justify-between py-2 border-b border-gray-50">
            <div><p className="text-sm font-semibold">{b.bank}</p><p className="text-xs text-gray-500">{b.account_number} — {b.account_name}</p></div>
            <button onClick={() => removeBank(i)} className="text-xs text-red-400 hover:underline">Hapus</button>
          </div>
        ))}
        {!showAddBank ? (
          <button onClick={() => setShowAddBank(true)} className="text-sm text-brand-600 hover:underline mt-2">+ Tambah rekening</button>
        ) : (
          <div className="mt-3 space-y-2 p-3 bg-gray-50 rounded-xl">
            <input className="input text-sm" placeholder="Nama bank (BCA, Mandiri, dll)" value={newBank.bank} onChange={e => setNewBank({...newBank, bank: e.target.value})} />
            <input className="input text-sm" placeholder="No rekening" value={newBank.account_number} onChange={e => setNewBank({...newBank, account_number: e.target.value})} />
            <input className="input text-sm" placeholder="Atas nama" value={newBank.account_name} onChange={e => setNewBank({...newBank, account_name: e.target.value})} />
            <div className="flex gap-2">
              <button onClick={addBank} className="btn-primary text-sm py-1.5">Simpan</button>
              <button onClick={() => setShowAddBank(false)} className="text-xs text-gray-400">Batal</button>
            </div>
          </div>
        )}
      </div>

      {/* Promo Codes */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">🎁 Kode Promo</h3>
        {promos.map(p => {
          const isExpired = p.valid_until && new Date(p.valid_until) < new Date();
          return (
            <div key={p.id} className="py-2.5 border-b border-gray-50 last:border-0">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-brand-600">{p.code}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${p.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                      {p.is_active ? 'Aktif' : 'Nonaktif'}
                    </span>
                    {isExpired && (
                      <span className="text-[10px] bg-red-100 text-red-600 px-1.5 py-0.5 rounded font-medium">
                        Expired
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-gray-400 flex flex-wrap items-center gap-1">
                    <span>{p.is_free ? 'FREE' : `-${p.discount_pct}%`}</span>
                    <span>·</span>
                    <span>{p.used_count}/{p.max_uses || '∞'} used</span>
                    {p.event_name && (
                      <>
                        <span>·</span>
                        <span className="text-amber-600">{p.event_name}</span>
                      </>
                    )}
                    <span>·</span>
                    <span>
                      {p.valid_until
                        ? `s.d. ${new Date(p.valid_until).toLocaleDateString('id-ID')}`
                        : 'Selamanya'}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => editingPromoId === p.id ? cancelEditPromo() : startEditPromo(p)}
                    className="text-xs text-brand-600 hover:underline font-medium"
                  >
                    {editingPromoId === p.id ? 'Tutup' : 'Edit'}
                  </button>
                  <button
                    onClick={() => togglePromoActive(p)}
                    className={`text-xs hover:underline ${p.is_active ? 'text-red-400' : 'text-green-600'}`}
                  >
                    {p.is_active ? 'Nonaktifkan' : 'Aktifkan'}
                  </button>
                </div>
              </div>

              {/* Inline Edit Form */}
              {editingPromoId === p.id && (
                <div className="mt-3 space-y-2.5 p-3 bg-gray-50 rounded-xl border border-gray-100">
                  <p className="text-xs font-semibold text-gray-700">Edit Promo: {p.code}</p>
                  <input
                    className="input text-sm"
                    placeholder="Kode promo (contoh: MERDEKA)"
                    value={editPromo.code}
                    onChange={e => setEditPromo({...editPromo, code: e.target.value.toUpperCase()})}
                  />
                  <div className="flex gap-2 items-center">
                    <label className="flex items-center gap-1 text-sm">
                      <input
                        type="checkbox"
                        checked={editPromo.is_free}
                        onChange={e => setEditPromo({...editPromo, is_free: e.target.checked, discount_pct: e.target.checked ? 100 : 0})}
                      /> Gratis
                    </label>
                    {!editPromo.is_free && (
                      <input
                        className="input text-sm w-28"
                        type="number"
                        min="1"
                        max="100"
                        placeholder="Diskon %"
                        value={editPromo.discount_pct}
                        onChange={e => setEditPromo({...editPromo, discount_pct: parseInt(e.target.value) || 0})}
                      />
                    )}
                  </div>
                  <input
                    className="input text-sm"
                    type="number"
                    min="0"
                    placeholder="Max penggunaan (kosongkan/0 = unlimited)"
                    value={editPromo.max_uses}
                    onChange={e => setEditPromo({...editPromo, max_uses: e.target.value})}
                  />
                  <input
                    className="input text-sm"
                    placeholder="Event (contoh: 17 Agustus)"
                    value={editPromo.event_name}
                    onChange={e => setEditPromo({...editPromo, event_name: e.target.value})}
                  />
                  <div>
                    <input
                      className="input text-sm"
                      type="number"
                      min="0"
                      placeholder="Perpanjang berlaku berapa hari dari sekarang"
                      value={editPromo.valid_days}
                      disabled={editPromo.clear_validity}
                      onChange={e => setEditPromo({...editPromo, valid_days: e.target.value})}
                    />
                    <label className="flex items-center gap-1.5 text-xs text-gray-500 mt-1.5">
                      <input
                        type="checkbox"
                        checked={editPromo.clear_validity}
                        onChange={e => setEditPromo({...editPromo, clear_validity: e.target.checked, valid_days: e.target.checked ? '' : editPromo.valid_days})}
                      /> Jadikan berlaku selamanya (hapus batas kedaluwarsa)
                    </label>
                  </div>
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={() => saveEditPromo(p.id)}
                      disabled={!editPromo.code.trim()}
                      className="btn-primary text-sm py-1.5 px-3 disabled:opacity-50"
                    >
                      Simpan Perubahan
                    </button>
                    <button
                      onClick={cancelEditPromo}
                      className="text-xs text-gray-400 hover:text-gray-600 px-2"
                    >
                      Batal
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
        {!showAddPromo ? (
          <button onClick={() => setShowAddPromo(true)} className="text-sm text-brand-600 hover:underline mt-2">+ Buat promo</button>
        ) : (
          <div className="mt-3 space-y-2 p-3 bg-gray-50 rounded-xl">
            <input className="input text-sm" placeholder="Kode promo (contoh: MERDEKA)" value={newPromo.code} onChange={e => setNewPromo({...newPromo, code: e.target.value})} />
            <div className="flex gap-2 items-center">
              <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={newPromo.is_free} onChange={e => setNewPromo({...newPromo, is_free: e.target.checked, discount_pct: e.target.checked ? 100 : 0})} /> Gratis</label>
              {!newPromo.is_free && <input className="input text-sm w-24" type="number" placeholder="Diskon %" value={newPromo.discount_pct} onChange={e => setNewPromo({...newPromo, discount_pct: parseInt(e.target.value)||0})} />}
            </div>
            <input className="input text-sm" type="number" placeholder="Max penggunaan (kosong=unlimited)" value={newPromo.max_uses} onChange={e => setNewPromo({...newPromo, max_uses: e.target.value})} />
            <input className="input text-sm" placeholder="Event (contoh: 17 Agustus)" value={newPromo.event_name} onChange={e => setNewPromo({...newPromo, event_name: e.target.value})} />
            <input className="input text-sm" type="number" placeholder="Berlaku berapa hari (kosong=forever)" value={newPromo.valid_days} onChange={e => setNewPromo({...newPromo, valid_days: e.target.value})} />
            <div className="flex gap-2">
              <button onClick={createPromo} disabled={!newPromo.code} className="btn-primary text-sm py-1.5 disabled:opacity-50">Buat</button>
              <button onClick={() => setShowAddPromo(false)} className="text-xs text-gray-400">Batal</button>
            </div>
          </div>
        )}
      </div>

      {/* Payment Orders */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-sm">💳 Payment Orders</h3>
          <div className="flex gap-1">
            {['', 'waiting_confirmation', 'pending', 'completed', 'rejected'].map(s => (
              <button key={s} onClick={() => setFilter(s)}
                className={`text-xs px-2 py-1 rounded-lg ${filter === s ? 'bg-brand-50 text-brand-600' : 'text-gray-400'}`}>
                {s || 'All'}
              </button>
            ))}
          </div>
        </div>
        {orders.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-4">Belum ada order</p>
        ) : orders.map(o => (
          <div key={o.id} className="py-3 border-b border-gray-50">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold">{o.user_name}</p>
                <p className="text-xs text-gray-400">{o.user_email} · {formatCurrency(o.amount)} · {new Date(o.created_at).toLocaleDateString('id-ID')}</p>
                {o.promo_code && <span className="text-xs text-amber-600">Promo: {o.promo_code} (-{o.discount_pct}%)</span>}
              </div>
              <div className="flex items-center gap-2">
                {o.proof_url && <a href={o.proof_url} target="_blank" className="text-xs text-blue-500 hover:underline">📸 Bukti</a>}
                {(o.status === 'waiting_confirmation' || o.status === 'pending') && (
                  <>
                    <button onClick={() => approveOrder(o.id)} className="text-xs px-2 py-1 bg-green-50 text-green-600 rounded-lg hover:bg-green-100">✅ Approve</button>
                    <button onClick={() => rejectOrder(o.id)} className="text-xs px-2 py-1 bg-red-50 text-red-400 rounded-lg hover:bg-red-100">❌ Reject</button>
                  </>
                )}
                {o.status === 'completed' && <span className="text-xs text-green-600">✅</span>}
                {o.status === 'rejected' && <span className="text-xs text-red-400">❌</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
