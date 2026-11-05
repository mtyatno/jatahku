import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { statusEmail, pesanVerifikasi } from '../lib/laporanView';
import KataSandiForm from './laporan/KataSandiForm';

const PARAM_VERIFIKASI = 'email_verifikasi';

// Pesan sesudah tautan verifikasi email; tampil di kartu apa pun keadaan pemuatan pengaturannya.
function PesanVerifikasi({ pesan }) {
  if (!pesan) return null;
  const warna = pesan.jenis === 'sukses' ? 'text-brand-600' : 'text-danger-400';
  return <p className={`text-sm ${warna}`} role="status">{pesan.teks}</p>;
}

// Tautan ke arsip laporan: di HP (tanpa sidebar) satu-satunya jalan ke /laporan selain notifikasi. Tetap tampil saat
// pengaturan gagal dimuat.
function LihatLaporan() {
  return (
    <Link to="/laporan" className="inline-block text-sm font-semibold text-brand-600 hover:underline">
      Lihat laporan
    </Link>
  );
}

// Kartu pengaturan laporan: status email + verifikasi, saklar email, dan kata sandi PDF.
export default function LaporanSettings() {
  const [pengaturan, setPengaturan] = useState(null);
  const [error, setError] = useState('');
  const [edit, setEdit] = useState(false);
  const [sukses, setSukses] = useState('');
  // Dibaca di initializer (bukan di effect: StrictMode menjalankan effect dua kali dan param dihapus di effect).
  const [pesanLink] = useState(() => pesanVerifikasi(new URLSearchParams(window.location.search).get(PARAM_VERIFIKASI)));
  const [mengirim, setMengirim] = useState(false);
  const [terkirimKe, setTerkirimKe] = useState('');
  const [errorKirim, setErrorKirim] = useState('');
  const [menyimpanEmail, setMenyimpanEmail] = useState(false);
  const [errorEmail, setErrorEmail] = useState('');

  const muat = () => api.getLaporanPengaturan().then(setPengaturan).catch((e) => setError(e.message));
  useEffect(() => { muat(); }, []);

  // Tautan "/settings#laporan" dari banner: halaman SPA tidak menggulir ke jangkar sendiri.
  useEffect(() => {
    if (window.location.hash === '#laporan') {
      document.getElementById('laporan')?.scrollIntoView({ block: 'start' });
    }
  }, []);

  // Hapus hanya ?email_verifikasi= dari URL; query lain, hash (#laporan) dan state riwayat react-router tetap.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (!params.has(PARAM_VERIFIKASI)) return;
    params.delete(PARAM_VERIFIKASI);
    const sisa = params.toString();
    const { pathname, hash } = window.location;
    window.history.replaceState(window.history.state, '', pathname + (sisa ? `?${sisa}` : '') + hash);
  }, []);

  const kirimVerifikasi = async () => {
    setMengirim(true);
    setErrorKirim('');
    setTerkirimKe('');
    try {
      await api.kirimVerifikasiEmail();
      setTerkirimKe(pengaturan.email);
    } catch (e) {
      setErrorKirim(e.message);
    } finally {
      setMengirim(false);
    }
  };

  const ubahEmailOn = async (nilai) => {
    const sebelumnya = pengaturan;
    setErrorEmail('');
    setMenyimpanEmail(true);
    setPengaturan({ ...pengaturan, email_on: nilai });
    try {
      setPengaturan(await api.ubahPengaturanLaporan({ email_on: nilai }));
    } catch (e) {
      setPengaturan(sebelumnya);
      setErrorEmail(e.message);
    } finally {
      setMenyimpanEmail(false);
    }
  };

  const tersimpan = () => {
    setEdit(false);
    setSukses('Kata sandi laporan disimpan');
    setTimeout(() => setSukses(''), 3000);
    muat();
  };

  if (error) {
    return (
      <div className="space-y-3">
        <PesanVerifikasi pesan={pesanLink} />
        <p className="text-sm text-danger-400">{error}</p>
        <LihatLaporan />
      </div>
    );
  }
  if (!pengaturan) {
    return (
      <div className="space-y-3">
        <PesanVerifikasi pesan={pesanLink} />
        <div className="h-12 animate-pulse rounded-lg bg-gray-100" />
      </div>
    );
  }
  const email = statusEmail(pengaturan);
  const diatur = !!pengaturan.kata_sandi_diatur;
  const label = diatur ? 'Ganti kata sandi' : 'Atur kata sandi';
  return (
    <div className="space-y-3">
      <PesanVerifikasi pesan={pesanLink} />
      <p className="text-sm text-gray-600">{email.teks}</p>
      {email.bisaVerifikasi && (
        <div className="space-y-2">
          <button type="button" onClick={kirimVerifikasi} disabled={mengirim} className="btn-outline text-sm py-2">
            Kirim tautan verifikasi
          </button>
          {terkirimKe && <p className="text-sm text-brand-600">Tautan verifikasi dikirim ke {terkirimKe}. Berlaku 24 jam.</p>}
          {errorKirim && <p className="text-sm text-danger-400">{errorKirim}</p>}
        </div>
      )}
      <label className="flex items-center gap-2 text-sm text-gray-600">
        <input
          type="checkbox"
          checked={!!pengaturan.email_on}
          disabled={menyimpanEmail}
          onChange={(e) => ubahEmailOn(e.target.checked)}
          className="w-4 h-4 rounded border-gray-300 text-brand-600"
        />
        Kirim laporan ke email
      </label>
      {errorEmail && <p className="text-sm text-danger-400">{errorEmail}</p>}
      <p className="text-sm text-gray-600">
        {diatur ? 'Kata sandi laporan sudah diatur.' : 'Belum ada kata sandi laporan.'}
      </p>
      {!edit ? (
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setEdit(true)} className="btn-outline text-sm py-2">{label}</button>
          {sukses && <span className="text-xs text-brand-600 animate-pulse">{sukses}</span>}
        </div>
      ) : (
        <KataSandiForm label={label} onSaved={tersimpan} onCancel={() => setEdit(false)} />
      )}
      <LihatLaporan />
    </div>
  );
}
