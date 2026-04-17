import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { formatCurrency } from '../lib/utils';

const TIMEZONES = [
  { value: 'Asia/Jakarta', label: 'WIB (Jakarta, GMT+7)' },
  { value: 'Asia/Makassar', label: 'WITA (Makassar, GMT+8)' },
  { value: 'Asia/Jayapura', label: 'WIT (Jayapura, GMT+9)' },
  { value: 'Asia/Singapore', label: 'Singapore (GMT+8)' },
  { value: 'Asia/Bangkok', label: 'Bangkok (GMT+7)' },
  { value: 'Asia/Tokyo', label: 'Tokyo (GMT+9)' },
  { value: 'Asia/Dubai', label: 'Dubai (GMT+4)' },
  { value: 'Europe/London', label: 'London (GMT+0)' },
  { value: 'Europe/Berlin', label: 'Berlin (GMT+1)' },
  { value: 'America/New_York', label: 'New York (GMT-5)' },
  { value: 'America/Los_Angeles', label: 'Los Angeles (GMT-8)' },
  { value: 'Australia/Sydney', label: 'Sydney (GMT+11)' },
];

function NotifPrefs() {
  const [prefs, setPrefs] = useState(null);
  const [saving, setSaving] = useState(false);
  const [dailyTime, setDailyTime] = useState('20:00');
  const [weeklyTime, setWeeklyTime] = useState('08:00');

  useEffect(() => {
    api.request('/notifications/preferences').then(r => r.ok ? r.json() : null).then(d => {
      if (d) {
        setPrefs(d);
        setDailyTime(d.daily_summary_time || '20:00');
        setWeeklyTime(d.weekly_summary_time || '08:00');
      }
    });
  }, []);

  const toggle = async (key) => {
    const updated = { ...prefs, [key]: !prefs[key] };
    setPrefs(updated);
    setSaving(true);
    await api.request('/notifications/preferences', {
      method: 'PUT',
      body: JSON.stringify(updated),
    });
    setSaving(false);
  };

  const saveTime = async (key, val) => {
    if (key === 'daily') setDailyTime(val);
    else setWeeklyTime(val);
    setSaving(true);
    await api.request('/notifications/preferences', {
      method: 'PUT',
      body: JSON.stringify({ ...prefs, [key + '_summary_time']: val }),
    });
    setSaving(false);
  };

  if (!prefs) return <p className="text-xs text-gray-400">Loading...</p>;

  const rows = [
    { label: 'Budget warning', key: 'budget_warning' },
    { label: 'Langganan jatuh tempo', key: 'subscription_due' },
    { label: 'Ringkasan harian', key: 'daily_summary' },
    { label: 'Ringkasan mingguan', key: 'weekly_summary' },
    { label: 'Cooling period selesai', key: 'cooling_ready' },
  ];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2 text-xs text-gray-400 font-medium px-1">
        <span></span><span className="text-center">Telegram</span><span className="text-center">WebApp</span>
      </div>
      {rows.map(r => (
        <div key={r.key} className="grid grid-cols-3 gap-2 items-center">
          <span className="text-sm text-gray-600">{r.label}</span>
          <label className="flex justify-center"><input type="checkbox" checked={prefs[r.key + '_tg']} onChange={() => toggle(r.key + '_tg')} className="w-4 h-4 rounded border-gray-300 text-brand-600" /></label>
          <label className="flex justify-center"><input type="checkbox" checked={prefs[r.key + '_web']} onChange={() => toggle(r.key + '_web')} className="w-4 h-4 rounded border-gray-300 text-brand-600" /></label>
        </div>
      ))}
      <div className="border-t border-gray-100 pt-3 mt-3 space-y-2">
        <p className="text-xs text-gray-400 font-medium">Jadwal ringkasan (sesuai timezone kamu):</p>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-600 w-32">Harian</span>
          <input type="time" className="input text-sm py-1 w-28" value={dailyTime} onChange={e => saveTime('daily', e.target.value)} />
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-600 w-32">Mingguan (Senin)</span>
          <input type="time" className="input text-sm py-1 w-28" value={weeklyTime} onChange={e => saveTime('weekly', e.target.value)} />
        </div>
      </div>
      {saving && <p className="text-xs text-brand-600 mt-2">Menyimpan...</p>}
    </div>
  );
}

export default function Settings() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  // Form states
  const [editName, setEditName] = useState(false);
  const [name, setName] = useState('');
  const [editEmail, setEditEmail] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [emailPwd, setEmailPwd] = useState('');
  const [editPwd, setEditPwd] = useState(false);
  const [currentPwd, setCurrentPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [tz, setTz] = useState('');
  const [cooling, setCooling] = useState('');
  const [dailyLimit, setDailyLimit] = useState('');
  const [defaultLocked, setDefaultLocked] = useState(false);
  const [paydayDay, setPaydayDay] = useState(1);
  const [msg, setMsg] = useState('');
  const [errMsg, setErrMsg] = useState('');

  // Link TG
  const [linkCode, setLinkCode] = useState(null);
  const [linkLoading, setLinkLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  // Link WA
  const [waStatus, setWaStatus] = useState({ linked: false });
  const [waCodeInput, setWaCodeInput] = useState('');
  const [waLinking, setWaLinking] = useState(false);
  const [waPhone, setWaPhone] = useState('');
  const [waSavingPhone, setWaSavingPhone] = useState(false);

  // Delete
  const [showDelete, setShowDelete] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState('');

  // Household
  const [members, setMembers] = useState([]);
  const [inviteCode, setInviteCode] = useState('');

  const load = async () => {
    const res = await api.request('/user/profile');
    if (res.ok) {
      const p = await res.json();
      setProfile(p);
      setName(p.name);
      setTz(p.timezone);
      setPaydayDay(p.payday_day || 1);
      setCooling(p.default_cooling_threshold || '');
      setDailyLimit(p.default_daily_limit || '');
      setDefaultLocked(p.default_is_locked);
    }
    const mRes = await api.request('/household/members');
    if (mRes.ok) setMembers(await mRes.json());
    setLoading(false);
    const waRes = await api.getWhatsAppStatus();
    setWaStatus(waRes);
    setWaPhone(waRes.phone || '');
  };

  useEffect(() => { load(); }, []);

  // Poll for TG link
  useEffect(() => {
    if (!linkCode || profile?.telegram_id) return;
    const interval = setInterval(async () => {
      const res = await api.request('/auth/me');
      if (res.ok) {
        const me = await res.json();
        if (me.telegram_id) window.location.reload();
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [linkCode, profile?.telegram_id]);

  const [inlineMsg, setInlineMsg] = useState({ key: '', text: '' });
  const flash = (m, key='global') => { setInlineMsg({ key, text: m }); setTimeout(() => setInlineMsg({ key: '', text: '' }), 3000); };
  const flashErr = (m, key='global') => { setInlineMsg({ key, text: '❌ ' + m }); setTimeout(() => setInlineMsg({ key: '', text: '' }), 3000); };
  const InlineFlash = ({ k }) => inlineMsg.key === k ? <span className="text-xs text-brand-600 ml-2 animate-pulse">{inlineMsg.text}</span> : null;

  const saveName = async () => {
    await api.request('/user/profile', { method: 'PUT', body: JSON.stringify({ name }) });
    setEditName(false); flash('Nama diperbarui', 'name'); load();
  };

  const saveEmail = async () => {
    const res = await api.request('/user/email', { method: 'PUT', body: JSON.stringify({ new_email: newEmail, password: emailPwd }) });
    if (res.ok) { setEditEmail(false); setNewEmail(''); setEmailPwd(''); flash('Email diperbarui', 'email'); load(); }
    else { const d = await res.json(); flashErr(d.detail || 'Gagal', 'email'); }
  };

  const savePwd = async () => {
    const res = await api.request('/user/password', { method: 'PUT', body: JSON.stringify({ current_password: currentPwd, new_password: newPwd }) });
    if (res.ok) { setEditPwd(false); setCurrentPwd(''); setNewPwd(''); flash('Password diperbarui', 'pwd'); }
    else { const d = await res.json(); flashErr(d.detail || 'Gagal', 'pwd'); }
  };

  const saveTz = async (val) => {
    setTz(val);
    await api.request('/user/profile', { method: 'PUT', body: JSON.stringify({ timezone: val }) });
    flash('Timezone diperbarui', 'tz');
  };

  const savePaydayDay = async (val) => {
    const day = parseInt(val);
    if (day < 1 || day > 31) return;
    setPaydayDay(day);
    await api.request('/user/profile', { method: 'PUT', body: JSON.stringify({ payday_day: day }) });
    flash('Tanggal gajian diperbarui', 'payday');
  };

  const saveBehavior = async () => {
    await api.request('/user/behavior-defaults', {
      method: 'PUT',
      body: JSON.stringify({
        default_cooling_threshold: cooling ? Number(cooling) : null,
        default_daily_limit: dailyLimit ? Number(dailyLimit) : null,
        default_is_locked: defaultLocked,
      }),
    });
    flash('Default behavior diperbarui', 'behavior');
  };

  const uploadPic = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    const baseUrl = api.baseUrl || (window.location.hostname === 'localhost' ? 'http://localhost:8000' : 'https://api.jatahku.com');
    const res = await fetch(baseUrl + '/user/profile-pic', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + api.token },
      body: form,
    });
    if (res.ok) { flash('Foto diperbarui'); load(); }
    else flashErr('Gagal upload. Max 2MB.');
  };

  const generateLinkCode = async () => {
    setLinkLoading(true);
    const res = await api.request('/auth/link/generate', { method: 'POST' });
    if (res.ok) { const data = await res.json(); setLinkCode(data.code); }
    setLinkLoading(false);
  };

  const linkWhatsApp = async () => {
    if (!waCodeInput.trim()) return;
    setWaLinking(true);
    const res = await api.linkWhatsApp(waCodeInput.trim());
    setWaLinking(false);
    if (res.ok) {
      setWaCodeInput('');
      flash('WhatsApp terhubung!', 'wa');
      load();
    } else {
      const d = await res.json();
      flashErr(d.detail || 'Kode tidak valid', 'wa');
    }
  };

  const unlinkWhatsApp = async () => {
    if (!confirm('Putuskan koneksi WhatsApp?')) return;
    const res = await api.unlinkWhatsApp();
    if (res.ok) { flash('WhatsApp diputus', 'wa'); load(); }
    else flashErr('Gagal memutus koneksi', 'wa');
  };

  const saveWaPhone = async () => {
    setWaSavingPhone(true);
    const res = await api.saveWhatsAppPhone(waPhone);
    setWaSavingPhone(false);
    if (res.ok) flash('Nomor HP disimpan', 'wa-phone');
    else flashErr('Format nomor tidak valid', 'wa-phone');
  };

  const generateInvite = async () => {
    const res = await api.request('/household/invite', { method: 'POST' });
    if (res.ok) { const d = await res.json(); setInviteCode(d.code); }
  };

  const exportData = async () => {
    try {
      const res = await api.request('/user/export-data');
      if (res.ok) {
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'jatahku-data-' + (profile?.name || 'user') + '.json';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        flash('Data berhasil didownload', 'data');
      }
    } catch (e) {
      flashErr('Gagal download data', 'data');
    }
  };

  const deleteAccount = async () => {
    if (deleteConfirm !== 'HAPUS') return;
    try {
      await exportData();
      await api.request('/user/account', { method: 'DELETE' });
      logout();
    } catch (e) {
      flashErr('Gagal hapus akun', 'data');
    }
  };

  const logoutAll = async () => {
    await api.request('/user/logout-all', { method: 'POST' });
    flash('Semua sesi di-logout');
    logout();
  };

  const roleLabel = (r) => ({ owner: 'Owner', admin: 'Admin', member: 'Member' }[r] || r);

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;
  if (!profile) return <div className="text-center py-12 text-gray-400">Error loading profile</div>;

  const plan = profile.plan || 'basic';
  const u = profile.usage;
  const l = profile.limits;

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-display font-bold">Settings</h1>



      {/* Profile */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">👤 Profil</h3>
        <div className="flex items-center gap-4 mb-4">
          <div className="relative group">
            {profile.profile_pic ? (
              <img src={profile.profile_pic} alt="" className="w-16 h-16 rounded-full object-cover border-2 border-gray-100" />
            ) : (
              <div className="w-16 h-16 rounded-full bg-brand-50 flex items-center justify-center text-2xl font-bold text-brand-600 border-2 border-gray-100">
                {profile.name?.charAt(0)?.toUpperCase() || '?'}
              </div>
            )}
            <label className="absolute inset-0 flex items-center justify-center bg-black/40 rounded-full opacity-0 group-hover:opacity-100 cursor-pointer transition-opacity">
              <span className="text-white text-xs font-medium">Ganti</span>
              <input type="file" accept="image/*" className="hidden" onChange={uploadPic} />
            </label>
          </div>
          <div className="flex-1">
            {!editName ? (
              <div className="flex items-center gap-2">
                <span className="font-semibold">{profile.name}</span>
                <button onClick={() => setEditName(true)} className="text-xs text-brand-600 hover:underline">Edit</button>
              </div>
            ) : (
              <div className="flex gap-2">
                <input className="input text-sm py-1.5 flex-1" value={name} onChange={e => setName(e.target.value)} />
                <button onClick={saveName} className="text-xs text-brand-600 font-medium">Simpan</button>
                <button onClick={() => { setEditName(false); setName(profile.name); }} className="text-xs text-gray-400">Batal</button>
              </div>
            )}
            <p className="text-xs text-gray-400 mt-0.5">{profile.email}</p>
          </div>
        </div>

        {/* Email */}
        <div className="border-t border-gray-100 pt-3 mt-3">
          {!editEmail ? (
            <div className="flex items-center justify-between">
              <div><p className="text-xs text-gray-400">Email</p><p className="text-sm">{profile.email}</p></div>
              <button onClick={() => setEditEmail(true)} className="text-xs text-brand-600 hover:underline">Ganti email</button>
            </div>
          ) : (
            <div className="space-y-2">
              <input className="input text-sm" placeholder="Email baru" value={newEmail} onChange={e => setNewEmail(e.target.value)} />
              <input className="input text-sm" type="password" placeholder="Password untuk konfirmasi" value={emailPwd} onChange={e => setEmailPwd(e.target.value)} />
              <div className="flex gap-2">
                <button onClick={saveEmail} disabled={!newEmail || !emailPwd} className="btn-primary text-sm py-1.5 disabled:opacity-50">Simpan</button>
                <button onClick={() => { setEditEmail(false); setNewEmail(''); setEmailPwd(''); }} className="text-xs text-gray-400">Batal</button>
              </div>
            </div>
          )}
        </div>

        {/* Password */}
        <div className="border-t border-gray-100 pt-3 mt-3">
          {!editPwd ? (
            <div className="flex items-center justify-between">
              <div><p className="text-xs text-gray-400">Password</p><p className="text-sm">••••••••</p></div>
              <button onClick={() => setEditPwd(true)} className="text-xs text-brand-600 hover:underline">Ganti password</button>
            </div>
          ) : (
            <div className="space-y-2">
              <input className="input text-sm" type="password" placeholder="Password lama" value={currentPwd} onChange={e => setCurrentPwd(e.target.value)} />
              <input className="input text-sm" type="password" placeholder="Password baru (min 6 karakter)" value={newPwd} onChange={e => setNewPwd(e.target.value)} />
              <div className="flex gap-2">
                <button onClick={savePwd} disabled={!currentPwd || newPwd.length < 6} className="btn-primary text-sm py-1.5 disabled:opacity-50">Simpan</button>
                <button onClick={() => { setEditPwd(false); setCurrentPwd(''); setNewPwd(''); }} className="text-xs text-gray-400">Batal</button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Telegram */}
      {!profile.telegram_id ? (
        <div className="card border-brand-200">
          <h3 className="font-semibold text-sm mb-2">📱 Hubungkan Telegram</h3>
          <p className="text-xs text-gray-500 mb-4">Catat pengeluaran secepat kirim chat. Ketik "kopi 35k" dan langsung tercatat!</p>
          <div className="bg-gray-50 rounded-xl p-4 mb-4 space-y-2">
            <div className="flex items-center gap-2 text-sm"><span>⚡</span><span>Catat pengeluaran dalam 3 detik</span></div>
            <div className="flex items-center gap-2 text-sm"><span>🔔</span><span>Notifikasi budget otomatis</span></div>
            <div className="flex items-center gap-2 text-sm"><span>📊</span><span>Ringkasan harian & mingguan</span></div>
          </div>
          {linkCode ? (
            <div className="space-y-4">
              <div className="bg-brand-50 rounded-xl p-4">
                <p className="text-sm font-semibold text-brand-700 mb-2">Langkah 1: Buka bot di Telegram</p>
                <a href={`https://t.me/JatahkuBot?start=link_${linkCode}`} target="_blank" rel="noreferrer"
                  onClick={() => {
                    // Also try tg:// to open app directly (hidden anchor, won't navigate page)
                    const a = document.createElement('a');
                    a.href = `tg://resolve?domain=JatahkuBot&start=link_${linkCode}`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                  }}
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-3 bg-blue-500 text-white text-sm font-semibold rounded-xl hover:bg-blue-600 transition-colors">
                  📱 Buka @JatahkuBot
                </a>
              </div>
              <div className="bg-gray-50 rounded-xl p-4">
                <p className="text-sm font-semibold text-gray-700 mb-2">Langkah 2: Kirim kode ini di chat bot</p>
                <div className="flex items-center gap-2">
                  <div className="flex-1 bg-white rounded-lg px-4 py-3 border border-gray-200">
                    <code className="font-mono text-lg font-bold text-brand-600">/link {linkCode}</code>
                  </div>
                  <button onClick={() => {navigator.clipboard.writeText('/link ' + linkCode); setCopied(true); setTimeout(() => setCopied(false), 2000);}}
                    className="px-4 py-3 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-500 hover:text-brand-600 hover:border-brand-400 transition-all whitespace-nowrap">
                    {copied ? '✅ Copied!' : '📋 Copy'}
                  </button>
                </div>
                <p className="text-xs text-gray-400 mt-2">Kode berlaku 5 menit</p>
              </div>
            </div>
          ) : (
            <button onClick={generateLinkCode} disabled={linkLoading}
              className="w-full btn-primary justify-center text-center disabled:opacity-50">
              {linkLoading ? 'Generating...' : '🔗 Generate Link Telegram'}
            </button>
          )}
        </div>
      ) : (
        <div className="card">
          <h3 className="font-semibold text-sm mb-2">📱 Telegram</h3>
          <div className="flex items-center justify-between">
            <span className="text-sm text-brand-600">✅ Terhubung (ID: {profile.telegram_id})</span>
          </div>
        </div>
      )}

      {/* WhatsApp */}
      {waStatus && !waStatus.linked ? (
        <div className="card border-brand-200">
          <h3 className="font-semibold text-sm mb-2">💬 Hubungkan WhatsApp</h3>
          <p className="text-xs text-gray-500 mb-4">
            Catat pengeluaran via WhatsApp dengan NLP yang sama seperti Telegram.
          </p>
          <div className="space-y-4">
            <div>
              <p className="text-sm font-medium text-gray-700 mb-1">Cara 1: Kode dari bot</p>
              <p className="text-xs text-gray-500 mb-2">
                Kirim <code className="bg-gray-100 px-1 rounded">/link</code> ke nomor WhatsApp Jatahku, lalu masukkan kode di bawah.
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  className="input flex-1"
                  placeholder="Masukkan kode 6 digit"
                  value={waCodeInput}
                  onChange={e => setWaCodeInput(e.target.value)}
                  maxLength={6}
                />
                <button
                  onClick={linkWhatsApp}
                  disabled={waLinking || waCodeInput.length !== 6}
                  className="btn-primary disabled:opacity-50 whitespace-nowrap"
                >
                  {waLinking ? '...' : 'Hubungkan'}
                </button>
              </div>
              <InlineFlash k="wa" />
            </div>
            <div className="border-t border-gray-100 pt-3">
              <p className="text-sm font-medium text-gray-700 mb-1">Cara 2: Nomor HP (auto-link)</p>
              <p className="text-xs text-gray-500 mb-2">
                Simpan nomor HP kamu. Bot akan otomatis mengenali saat pesan pertama masuk.
              </p>
              <div className="flex gap-2">
                <input
                  type="tel"
                  className="input flex-1"
                  placeholder="08123456789"
                  value={waPhone}
                  onChange={e => setWaPhone(e.target.value)}
                />
                <button
                  onClick={saveWaPhone}
                  disabled={waSavingPhone || !waPhone}
                  className="btn-outline disabled:opacity-50 whitespace-nowrap"
                >
                  {waSavingPhone ? '...' : 'Simpan'}
                </button>
              </div>
              <InlineFlash k="wa-phone" />
            </div>
          </div>
        </div>
      ) : waStatus?.linked ? (
        <div className="card">
          <h3 className="font-semibold text-sm mb-2">💬 WhatsApp</h3>
          <div className="flex items-center justify-between">
            <div>
              <span className="text-sm text-brand-600">✅ Terhubung</span>
              {waStatus.phone && <p className="text-xs text-gray-500 mt-0.5">+{waStatus.phone}</p>}
            </div>
            <button onClick={unlinkWhatsApp} className="text-xs text-gray-400 hover:text-danger-400">
              Putuskan
            </button>
          </div>
        </div>
      ) : null}

      {/* Household */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">👨‍👩‍👧 Household</h3>
        <div className="space-y-2 mb-3">
          {members.map((m, i) => (
            <div key={i} className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-full bg-brand-50 flex items-center justify-center text-xs font-bold text-brand-600">
                  {m.name?.charAt(0)?.toUpperCase() || '?'}
                </div>
                <span>{m.name}</span>
              </div>
              <span className={`text-xs px-2 py-0.5 rounded-full ${m.role === 'owner' ? 'bg-amber-50 text-amber-600' : 'bg-gray-100 text-gray-500'}`}>{roleLabel(m.role)}</span>
            </div>
          ))}
        </div>
        {inviteCode ? (
          <div className="bg-gray-50 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400 mb-1">Kode invite (24 jam):</p>
            <code className="font-mono text-lg font-bold text-brand-600">{inviteCode}</code>
          </div>
        ) : (
          <button onClick={generateInvite} className="text-sm text-brand-600 hover:underline">+ Invite anggota</button>
        )}
      </div>

      {/* Payday Day */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-1">📅 Tanggal Gajian</h3>
        <p className="text-xs text-gray-400 mb-3">Periode budget dihitung dari tanggal ini setiap bulan.</p>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">Tanggal</span>
            <input
              type="number" min="1" max="31"
              className="input text-sm w-20 text-center"
              value={paydayDay}
              onChange={e => savePaydayDay(e.target.value)}
            />
            <span className="text-sm text-gray-600">setiap bulan</span>
          </div>
          <InlineFlash k="payday" />
        </div>
        <p className="text-xs text-gray-400 mt-2">
          Contoh: gajian tgl 25 → periode 25 Mar – 24 Apr
        </p>
      </div>

      {/* Timezone */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">🕐 Timezone</h3>
        <div className="flex items-center gap-2">
          <select className="input text-sm flex-1" value={tz} onChange={e => saveTz(e.target.value)}>
            {TIMEZONES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          <InlineFlash k="tz" />
        </div>
      </div>

      {/* Default Behavior Controls */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-1">🛡️ Default Behavior Controls</h3>
        <p className="text-xs text-gray-400 mb-4">Setting default untuk amplop baru. Bisa diubah per amplop.</p>
        <div className="space-y-3">
          <div>
            <label className="text-sm text-gray-600">Cooling threshold (Rp)</label>
            <input className="input text-sm mt-1" type="number" placeholder="Contoh: 500000" value={cooling} onChange={e => setCooling(e.target.value)} />
            <p className="text-xs text-gray-400 mt-1">Transaksi di atas jumlah ini harus tunggu 24 jam</p>
          </div>
          <div>
            <label className="text-sm text-gray-600">Daily limit (Rp)</label>
            <input className="input text-sm mt-1" type="number" placeholder="Contoh: 100000" value={dailyLimit} onChange={e => setDailyLimit(e.target.value)} />
            <p className="text-xs text-gray-400 mt-1">Maksimal pengeluaran per hari per amplop</p>
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input type="checkbox" checked={defaultLocked} onChange={e => setDefaultLocked(e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-brand-600" />
            Kunci amplop baru secara default
          </label>
          <div className="flex items-center gap-2">
            <button onClick={saveBehavior} className="btn-primary text-sm py-2">Simpan default</button>
            <InlineFlash k="behavior" />
          </div>
        </div>
      </div>

      {/* Notifications */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">🔔 Notifikasi</h3>
        <NotifPrefs />
      </div>

      {/* Plan & Usage */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-sm">📋 Plan & Usage</h3>
          <span className={`px-3 py-1 rounded-full text-xs font-bold ${plan === 'pro' ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-600'}`}>
            {plan === 'pro' ? '⭐ Pro' : 'Free'}
          </span>
        </div>
        <div className="space-y-2">
          <UsageBar label="Amplop" used={u.envelopes} limit={l.envelopes} />
          <UsageBar label="Transaksi bulan ini" used={u.txn_this_month} limit={l.txn_per_month} />
          <UsageBar label="Langganan" used={u.recurring} limit={l.recurring} />
        </div>
        {plan === 'basic' && (
          <a href="/upgrade" className="mt-4 w-full btn-primary text-center justify-center text-sm py-2.5 block">
            ⭐ Upgrade ke Pro — Rp79.000 sekali bayar
          </a>
        )}
      </div>

      {/* Session & Security */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">🔐 Keamanan</h3>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm">Logout semua perangkat</p>
            <p className="text-xs text-gray-400">Keluar dari semua sesi aktif</p>
          </div>
          <button onClick={logoutAll} className="text-sm text-amber-600 hover:underline">Logout semua</button>
        </div>
      </div>

      {/* Data & Account */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">📦 Data & Akun</h3>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm">Download semua data</p>
              <p className="text-xs text-gray-400">Export dalam format JSON</p>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={exportData} className="text-sm text-brand-600 hover:underline">Download</button>
              <InlineFlash k="data" />
            </div>
          </div>
          <div className="border-t border-gray-100 pt-3">
            {!showDelete ? (
              <button onClick={() => setShowDelete(true)} className="text-sm text-red-400 hover:underline">Hapus akun saya</button>
            ) : (
              <div className="bg-red-50 rounded-xl p-4 space-y-3">
                <p className="text-sm font-semibold text-red-600">⚠️ Hapus akun?</p>
                <p className="text-xs text-red-500">Semua data kamu akan dihapus permanen. Data akan di-download otomatis sebelum dihapus.</p>
                <input className="input text-sm border-red-200" placeholder='Ketik "HAPUS" untuk konfirmasi'
                  value={deleteConfirm} onChange={e => setDeleteConfirm(e.target.value)} />
                <div className="flex gap-2">
                  <button onClick={deleteAccount} disabled={deleteConfirm !== 'HAPUS'}
                    className="px-4 py-2 bg-red-500 text-white text-sm font-medium rounded-xl disabled:opacity-50">Hapus permanen</button>
                  <button onClick={() => { setShowDelete(false); setDeleteConfirm(''); }} className="text-xs text-gray-400">Batal</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Logout */}
      <div className="card">
        <button onClick={logout} className="text-sm text-red-400 hover:underline">Logout dari Jatahku</button>
      </div>
    </div>
  );
}

function UsageBar({ label, used, limit }) {
  const unlimited = limit === -1;
  const pct = unlimited ? 0 : Math.min(Math.round((used / limit) * 100), 100);
  const color = pct >= 90 ? 'bg-red-400' : pct >= 70 ? 'bg-amber-400' : 'bg-brand-400';
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-gray-500">{label}</span>
        <span className="text-gray-600 font-medium">{used}{unlimited ? '' : ` / ${limit}`}</span>
      </div>
      {!unlimited && (
        <div className="h-1.5 bg-gray-100 rounded-full">
          <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
        </div>
      )}
      {unlimited && <p className="text-xs text-brand-600">Unlimited ✨</p>}
    </div>
  );
}
