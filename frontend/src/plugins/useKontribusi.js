// Kontribusi Fitur Tambahan untuk ruang aktif (Plugin H3). Dimuat sekali oleh Layout dan dibagikan lewat konteks Outlet.
//
// - Sumber: GET /plugins/contributions (menu, aksi cepat, halaman, kartu) dan GET /plugins (ada katalog atau tidak, untuk
//   pintu Fitur Tambahan). Server yang memutuskan: status per ruang, saklar darurat, flag, peran.
// - Karyawan tidak memanggil keduanya (server menolak, 403) dan tidak pernah mendapat kontribusi (keputusan H3 B).
//   U4: yang ia dapat hanya kartu Fitur Tambahan `untuk: "karyawan"` dari katalog kartunya sendiri
//   (GET /dashboard/cards, sudah disaring server per peran); kartu itu didaftarkan ke CardRegistry dan kuncinya
//   dibagikan sebagai `kartuKaryawan` supaya Beranda karyawan menggambar ulang. Menu, aksi, dan halaman tetap kosong.
// - Cache per user dan per ruang (akhiran ruang dari localCache, ADR-P16): menu plugin satu ruang tidak pernah tampil
//   di ruang lain; ganti ruang memuat ulang halaman. Offline memakai cache; ditolak server = kosong.
// - Event `jatahku:plugin-berubah` (sesudah pasang, jeda, copot) memuat ulang.
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { loadCache, saveCache } from '../lib/localCache';
import { KONTRIBUSI_KOSONG, kontribusiDariKatalog, rapikanKontribusi } from '../lib/pluginHost';
import { daftarkanKartuPlugin } from './kartu';

export const EVENT_PLUGIN_BERUBAH = 'jatahku:plugin-berubah';
const KOSONG = { kontribusi: KONTRIBUSI_KOSONG, katalogAda: false, siap: false, kartuKaryawan: '' };

export function useKontribusiPlugin({ userId, karyawan, menungguPeran }) {
  const [state, setState] = useState(KOSONG);

  useEffect(() => {
    if (!userId || menungguPeran) return undefined;
    if (karyawan) {
      let hidup = true;
      const kunciKartu = `plugin_kartu_karyawan:${userId}`;
      const pasangKartu = (defs) => {
        const k = kontribusiDariKatalog(defs);
        daftarkanKartuPlugin(k);
        setState({ ...KOSONG, siap: true, kartuKaryawan: k.cards.map(c => c.key).join(',') });
      };
      pasangKartu(loadCache(kunciKartu));
      api.kartuBeranda().then((r) => {
        if (!hidup) return;
        // Jaringan putus (status 0): pertahankan cache. Ditolak server (403, di luar jam kerja): tanpa kartu plugin.
        if (r.ok) { pasangKartu(r.data); saveCache(kunciKartu, r.data); } else if (r.status !== 0) pasangKartu(null);
      });
      return () => { hidup = false; };
    }
    let live = true;
    const kunci = `plugin_kontribusi:${userId}`;
    let sekarang = KOSONG;
    const pasang = (s) => {
      // Kartu didaftarkan sebelum state berubah, supaya render berikutnya sudah mengenal kartu plugin.
      daftarkanKartuPlugin(s.kontribusi);
      sekarang = s;
      setState(s);
    };
    const cache = loadCache(kunci);
    if (cache) pasang({ kontribusi: rapikanKontribusi(cache.kontribusi), katalogAda: !!cache.katalogAda, siap: true });

    const muat = async () => {
      const [k, kat] = await Promise.all([api.kontribusiPlugin(), api.katalogPlugin()]);
      if (!live) return;
      // Jaringan putus (status 0): pertahankan yang ada. Ditolak server (403, 404): tidak ada kontribusi.
      const kontribusi = k.ok ? rapikanKontribusi(k.data) : (k.status === 0 ? sekarang.kontribusi : KONTRIBUSI_KOSONG);
      const katalogAda = kat.ok ? Array.isArray(kat.data) && kat.data.length > 0
        : (kat.status === 0 ? sekarang.katalogAda : false);
      const baru = { kontribusi, katalogAda, siap: true };
      pasang(baru);
      if (k.ok || k.status !== 0) saveCache(kunci, { kontribusi, katalogAda });
    };
    muat();
    window.addEventListener(EVENT_PLUGIN_BERUBAH, muat);
    return () => {
      live = false;
      window.removeEventListener(EVENT_PLUGIN_BERUBAH, muat);
    };
  }, [userId, karyawan, menungguPeran]);

  return state;
}
