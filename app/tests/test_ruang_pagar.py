"""Plugin R2 — pagar supaya refactor `ruang_aktif` tidak bocor lagi, dan skrip paritas produksi.

1. Tidak ada kueri "household milik user" baru di luar `app/services/ruang.py`. Kueri keanggotaan
   langsung (`HouseholdMember.user_id == …`) hanya boleh di tempat yang memang bekerja per user atau
   per household tertentu (daftar di bawah, dengan alasannya). Titik baru harus memakai
   `ruang_aktif` / `ruang_tulis` (route) atau `ruang_keluarga` (bot, job).
2. Bot tidak pernah memakai header ruang (chat selalu ruang keluarga, ADR-P2).
3. `app/scripts/ruang_paritas.py`: user lama mendapat household yang sama; user dengan ruang usaha
   tetap mendapat ruang keluarga; kode keluar 1 bila ada yang berbeda.

Run: python -m unittest app.tests.test_ruang_pagar -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import pathlib
import re
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone

APP = pathlib.Path(__file__).resolve().parents[1]
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

# berkas → jumlah kemunculan `HouseholdMember.user_id ==` yang diizinkan, dan alasannya.
DIIZINKAN = {
    "services/ruang.py": 3,              # penentu ruang itu sendiri
    "services/peran.py": 2,              # peran user di ruang tertentu (R5, batasan karyawan) + owner ruang tertentu (join)
    "services/merge.py": 3,              # gabung akun: keanggotaan per user (ruang keluarga + hapus akun sumber)
    "services/account_deletion.py": 1,   # hapus akun: semua keanggotaan user
    "services/kotak_struk/view.py": 1,   # cek user masih anggota household item tertentu
    "services/recurring_processor.py": 1,  # anggota household amplop tertentu (join)
    "services/advisor/snapshot.py": 1,   # nama anggota household tertentu (join)
    "services/household_cycle.py": 1,    # anggota household tertentu (join): cermin payday di heal/set_household_payday
    "api/routes/household.py": 3,
    "api/routes/ruang.py": 1,            # satu anggota tertentu di ruang tertentu (R5, kelola anggota)        # daftar anggota (join) + cek sudah anggota household tujuan
    "api/routes/admin.py": 1,            # panel admin: ruang keluarga user (filter type)
    "api/routes/user_settings.py": 1,    # peran user di ruang yang di-reset
    "bot/household_cmd.py": 1,           # cek sudah anggota household tujuan
    "scripts/ruang_paritas.py": 1,       # meniru kueri lama untuk dibandingkan
}


def _sumber():
    for p in APP.rglob("*.py"):
        rel = p.relative_to(APP).as_posix()
        if rel.startswith("tests/"):
            continue
        yield rel, p.read_text()


class PagarSumberTests(unittest.TestCase):
    def test_tidak_ada_kueri_keanggotaan_baru(self):
        hitung = Counter()
        for rel, teks in _sumber():
            n = len(re.findall(r"HouseholdMember\.user_id\s*==", teks))
            if n:
                hitung[rel] = n
        self.assertEqual(dict(hitung), DIIZINKAN,
                         "kueri keanggotaan baru/lenyap: pakai app/services/ruang.py, atau perbarui DIIZINKAN "
                         "dengan alasan")

    def test_tidak_ada_helper_household_lama(self):
        for rel, teks in _sumber():
            for nama in ("get_household_id", "_get_hid", "_get_household_id"):
                self.assertNotRegex(teks, rf"\b{nama}\b", f"{rel} memakai helper lama {nama}")

    def test_bot_tidak_membaca_header_ruang(self):
        for rel, teks in _sumber():
            if rel.startswith("bot/"):
                for nama in ("ruang_aktif", "ruang_tulis", "RuangAktif", "RuangTulis", "X-Jatahku-Ruang"):
                    self.assertNotIn(nama, teks, f"{rel}: chat selalu ruang keluarga (ADR-P2)")

    def test_tulis_dengan_ruang_aktif_hanya_pengecualian_tercatat(self):
        """Sejak R3 route tulis menentukan ruang dari objeknya (lihat `test_setiap_route_tulis_punya_sumber_ruang`).
        `ruang_aktif` di route non-GET hanya untuk POST yang sekadar membaca, data milik user/viewer sendiri per
        ruang, atau objek baru tanpa induk (keputusan A, R3). Menambah baris di sini butuh alasan (review
        keamanan PR #166, #171)."""
        from fastapi.routing import APIRoute
        from app.main import app
        from app.services import ruang

        diizinkan = {
            ("POST", "/dashboard/data"),                      # hanya membaca
            ("POST", "/balance-check/preview"),               # hanya membaca
            ("POST", "/advisor/allocation-recommendation"),   # hanya membaca
            ("PUT", "/dashboard/layout"),                     # tata letak milik user per ruang
            ("POST", "/advisor/dismiss"),                     # status per viewer (Redis), bukan data ruang
            ("DELETE", "/advisor/dismiss"),                   # idem
            # R3, keputusan A: objek baru tanpa induk → ruang dari header yang sah (tanpa header = keluarga).
            ("POST", "/envelopes/"), ("POST", "/envelopes/groups"),
            ("POST", "/incomes/"),                            # tanpa alokasi; dengan alokasi = ruang amplopnya
            ("POST", "/user/reset"), ("POST", "/snapshots/recompute"),
            ("POST", "/balance-check/apply"),                 # cocokkan saldo seluruh ruang
            ("POST", "/advisor/plan"), ("POST", "/advisor/execute"),  # rencana atas amplop satu ruang
            ("POST", "/transactions/suggest-envelope"), ("POST", "/transactions/suggest-envelopes"),  # saran, R7
        }

        def pakai(dependant, fn):
            return any(d.call is fn or pakai(d, fn) for d in dependant.dependencies)

        ditemukan = set()
        for r in app.routes:
            if not isinstance(r, APIRoute):
                continue
            for m in r.methods - {"GET", "HEAD"}:
                if pakai(r.dependant, ruang.ruang_aktif):
                    ditemukan.add((m, r.path))
        self.assertEqual(ditemukan, diizinkan)

    def test_setiap_route_tulis_punya_sumber_ruang(self):
        """Setiap route non-GET masuk tepat satu kelompok (review keamanan PR #171):
        - `aktif`: dependency `ruang_aktif` (daftar izin di tes sebelumnya);
        - `tulis`: dependency `ruang_tulis` (hanya undangan anggota, ruang keluarga);
        - `objek`: badan handler memanggil pembantu ruang objek (`ruang_objek`, `ruang_amplop`,
          `ruang_amplop_satu`, `_ruang_*`, `ruang_cek`) — ruang dari baris DB lalu keanggotaan dicek;
        - `tanpa`: tidak menyentuh data ruang, atau ruangnya ditentukan jalur lain yang tercatat di bawah.
        Route tulis baru yang tidak masuk satu pun kelompok gagal di sini, jadi tidak bisa lupa menentukan ruang."""
        import inspect
        from fastapi.routing import APIRoute
        from app.main import app
        from app.services import ruang

        objek = {
            ("POST", "/balance-check/{check_id}/undo"),
            ("PATCH", "/envelopes/groups/{group_id}"), ("DELETE", "/envelopes/groups/{group_id}"),
            ("POST", "/envelopes/transfer"), ("PUT", "/envelopes/{envelope_id}"), ("DELETE", "/envelopes/{envelope_id}"),
            ("POST", "/goals/"), ("PUT", "/goals/{goal_id}"), ("DELETE", "/goals/{goal_id}"),
            ("PUT", "/kotak-struk/merchants/{merchant_id}"),
            ("POST", "/recurring/"), ("PUT", "/recurring/{rec_id}"), ("DELETE", "/recurring/{rec_id}"),
            ("POST", "/recurring/{rec_id}/mark-paid"), ("POST", "/recurring/{rec_id}/pay"),
            ("POST", "/recurring/{rec_id}/skip"),
            ("POST", "/transactions/"), ("POST", "/transactions/batch"), ("DELETE", "/transactions/{txn_id}"),
            ("POST", "/incomes/"),   # juga `aktif`: dengan alokasi = ruang amplop, tanpa alokasi = header
            # R5: ruang dari path, peran owner/admin dari baris keanggotaan (`_ruang_kelola`).
            ("PATCH", "/ruang/{rid}/anggota/{uid}"), ("DELETE", "/ruang/{rid}/anggota/{uid}"),
            ("PUT", "/ruang/{rid}/anggota/{uid}/batasan"), ("POST", "/ruang/{rid}/undangan"),
            ("POST", "/ruang/{rid}/persetujuan/{draf_id}/setujui"), ("POST", "/ruang/{rid}/persetujuan/{draf_id}/tolak"),
        }
        tulis = {("POST", "/household/invite")}
        # Awalan yang tidak menyentuh data ruang: panel admin (require_admin), akun dan sesi, laporan galat klien,
        # chat (bot memakai ruang_keluarga, ADR-P2), notifikasi dan pembayaran per user, profil user, webhook.
        tanpa_awalan = ("/admin/", "/auth/", "/app/errors", "/bot/chat/", "/notifications/", "/payment/", "/user/",
                        "/webhook/")
        tanpa = {
            ("POST", "/household/join"),                       # kode undangan; hanya ruang keluarga (review #166)
            ("POST", "/ruang/gabung"),                         # kode undangan ruang usaha (R5): ruang dari kodenya
            ("POST", "/kotak-struk/"),                         # unggah bukti: ruang keluarga di intake (R7)
            ("POST", "/kotak-struk/{item_id}/saran"),          # item milik user (`_owned_item`)
            ("POST", "/kotak-struk/{item_id}/lewati"),         # item milik user (`_owned_item`)
            ("POST", "/transactions/scan-receipt"),            # baca struk lewat Kotak Struk (ruang keluarga, R7)
            ("POST", "/transactions/scan-receipt/{scan_id}/feedback"),  # scan milik user
            ("POST", "/transactions/transcribe"),              # suara → teks, tanpa data ruang
            ("POST", "/snapshots/run"), ("POST", "/snapshots/daily-summary"),        # admin
            ("POST", "/snapshots/weekly-summary"), ("POST", "/snapshots/process-recurring"),  # admin
        }
        pembantu = re.compile(r"\b(ruang_objek|ruang_amplop|ruang_amplop_satu|_ruang_\w+|ruang_cek)\(")

        def pakai(dependant, fn):
            return any(d.call is fn or pakai(d, fn) for d in dependant.dependencies)

        tanpa_kelompok, objek_tanpa_pembantu = [], []
        for r in app.routes:
            if not isinstance(r, APIRoute):
                continue
            for m in r.methods - {"GET", "HEAD"}:
                kunci = (m, r.path)
                if kunci in objek:
                    # Route yang mendelegasikan ke jalur pencatatan bersama (R5: dipakai juga persetujuan draf).
                    delegasi = {("POST", "/transactions/"): "catat_transaksi"}.get(kunci)
                    fn = getattr(inspect.getmodule(r.endpoint), delegasi) if delegasi else r.endpoint
                    if not pembantu.search(inspect.getsource(fn)):
                        objek_tanpa_pembantu.append(kunci)
                    continue
                if pakai(r.dependant, ruang.ruang_aktif) or pakai(r.dependant, ruang.ruang_tulis):
                    if pakai(r.dependant, ruang.ruang_tulis) and kunci not in tulis:
                        tanpa_kelompok.append(kunci)
                    continue
                if kunci in tanpa or r.path.startswith(tanpa_awalan) and r.path != "/user/reset":
                    continue
                tanpa_kelompok.append(kunci)
        self.assertEqual(objek_tanpa_pembantu, [], "route 'objek' tanpa pembantu ruang objek")
        self.assertEqual(sorted(tanpa_kelompok), [], "route tulis tanpa sumber ruang yang tercatat")

    def test_route_ber_ruang_memakai_parameter_keyword_only(self):
        # `hid=Depends(...)` dengan nilai bawaan membuat pemanggil langsung meneruskan objek Depends.
        for rel, teks in _sumber():
            if rel.startswith("api/routes/"):
                self.assertNotRegex(teks, r"=\s*Depends\(ruang_(aktif|tulis)\)", rel)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RuangParitasScriptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.core.database import Base
        import app.models.models  # noqa: F401 — daftarkan tabel ke metadata
        self.engine = create_async_engine("sqlite+aiosqlite://")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def _user(self, db, *ruang):
        from app.models.models import Household, HouseholdMember, HouseholdRole, User
        u = User(name="u")
        db.add(u)
        await db.flush()
        for i, tipe in enumerate(ruang):
            hh = Household(name=f"h{i}", type=tipe)
            db.add(hh)
            await db.flush()
            db.add(HouseholdMember(user_id=u.id, household_id=hh.id, role=HouseholdRole.owner,
                                   created_at=datetime.now(timezone.utc) - timedelta(days=10 - i)))
        await db.flush()
        return u

    async def test_status_per_user(self):
        from app.scripts.ruang_paritas import periksa
        async with self.Session() as db:
            lama = await self._user(db, "rumah_tangga")
            tanpa = await self._user(db)
            dua = await self._user(db, "usaha", "rumah_tangga")
            ganda = await self._user(db, "rumah_tangga", "rumah_tangga")
            await db.commit()
            hasil = {k: await periksa(u, db) for k, u in
                     (("lama", lama), ("tanpa", tanpa), ("dua", dua), ("ganda", ganda))}
        self.assertEqual(hasil["lama"]["status"], "ok")
        self.assertEqual(hasil["lama"]["lama"], hasil["lama"]["baru"])
        self.assertEqual(hasil["tanpa"]["status"], "tanpa")
        self.assertEqual(hasil["dua"]["status"], "ok")          # kode lama galat, yang baru = keluarga
        self.assertEqual(hasil["dua"]["lama"], "ganda")
        self.assertEqual(hasil["ganda"]["status"], "beda")      # dua ruang keluarga perlu dirapikan


if __name__ == "__main__":
    unittest.main()
