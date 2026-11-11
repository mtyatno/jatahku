"""Review keamanan PR #205 (ruang usaha tanpa pengeluaran privat): probe dan pengunci temuan.

Melengkapi `test_privat_ruang_usaha.py` (jalur utama). Yang dikunci di sini:
1. Jenis ruang diambil dari amplop: header `X-Jatahku-Ruang` atau `ruang_id` di body tidak mengubah keputusannya,
   ke dua arah (ruang usaha tetap ditolak, ruang keluarga tetap boleh privat).
2. Kirim ulang `client_ref` bertanda privat tidak mengubah catatan terbuka yang sudah ada dan tidak mencatat dua kali;
   kirim ulang draf bertanda privat tetap draf terbuka yang sama.
3. Bukti Kotak Struk (`receipt_item_id`) tidak terklaim saat kirimannya ditolak, dan masih bisa dicatat sesudahnya.
4. Temuan R1: transaksi tertunda lama (`PendingTransaction`) bertanda privat di ruang usaha dikonfirmasi terbuka.
5. Temuan R2: `/transactions/batch` tidak membedakan amplop pribadi anggota lain dari amplop yang tidak ada lewat
   tanda privat (urutan pemeriksaan sama dengan `POST /transactions/`).
6. Temuan S2: lapis kedua kamus ruang lewat route (bukan hanya `_after_saved`): bila lapis pertama hilang, catatan
   privat tetap tidak mengajari kamus ruang, lewat `POST /transactions/` maupun `/batch`.
7. Pagar: setiap tempat yang membuat `Transaction` / `PendingTransaction` / `RuangDraf` dengan `is_private` selain
   `False` harus terdaftar di `PENULIS_PRIVAT`, supaya jalur tulis baru tidak melewati aturan ruang usaha.

Run: python -m unittest app.tests.test_privat_ruang_usaha_review -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import ast
import importlib.util
import pathlib
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from unittest.mock import AsyncMock, patch

APP = pathlib.Path(__file__).resolve().parents[1]
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

if HAS_AIOSQLITE:
    from sqlalchemy import select

    from app.tests import test_ruang_peran as r5
    from app.models.models import (
        Envelope, HouseholdType, PendingTransaction, PendingTransactionStatus, ReceiptScan, RuangDraf, RuangKamus,
        Transaction, TransactionSource,
    )
    from app.services import ruang
    from app.services.behavior import confirm_pending

KODE = "privat_tidak_tersedia"

# berkas → jumlah pembuatan `Transaction(...)`, `PendingTransaction(...)`, atau `RuangDraf(...)` yang mengisi
# `is_private` dengan nilai selain `False`, dan di mana aturan ruang usaha ditegakkan untuknya.
PENULIS_PRIVAT = {
    "api/routes/transactions.py": 2,   # catat_transaksi + /batch: ditolak 422 / per baris sebelum sampai ke sini
    "services/behavior.py": 2,         # pending lama: dibuat (tidak ada pemanggil lagi) + confirm_pending (terbuka di ruang usaha)
    "services/peran.py": 1,            # buat_draf: pemanggilnya (transactions.py) sudah menolak privat di ruang usaha
}
MODEL_BERPRIVAT = {"Transaction", "PendingTransaction", "RuangDraf"}


class PagarPenulisPrivatTests(unittest.TestCase):
    def test_penulis_is_private_terdaftar(self):
        hitung = Counter()
        for p in APP.rglob("*.py"):
            rel = p.relative_to(APP).as_posix()
            if rel.startswith("tests/") or "is_private" not in (teks := p.read_text()):
                continue
            for node in ast.walk(ast.parse(teks)):
                if not isinstance(node, ast.Call):
                    continue
                nama = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if nama not in MODEL_BERPRIVAT:
                    continue
                for kw in node.keywords:
                    if kw.arg == "is_private" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                        hitung[rel] += 1
        self.assertEqual(dict(hitung), PENULIS_PRIVAT,
                         "penulis `is_private` baru/lenyap: jalur tulis pengeluaran di ruang usaha tidak boleh privat "
                         "(AGENTS.md, Kontrak visibilitas); tegakkan aturannya, lalu perbarui PENULIS_PRIVAT")

    def test_bawaan_model_terbuka(self):
        """Bot, chat web, langganan, dan advisor membuat `Transaction` tanpa `is_private`: bawaannya harus terbuka."""
        from app.models.models import Transaction as T
        self.assertIs(T.__table__.c.is_private.default.arg, False)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class PrivatRuangUsahaReviewTests(unittest.IsolatedAsyncioTestCase):
    if HAS_AIOSQLITE:
        asyncSetUp = r5.RuangPeranTests.asyncSetUp
        _isi, _req, _batasan, _hitung = (r5.RuangPeranTests._isi, r5.RuangPeranTests._req,
                                         r5.RuangPeranTests._batasan, r5.RuangPeranTests._hitung)

    def body(self, env, ket, privat=True, **kw):
        return {"envelope_id": str(env), "amount": "25000", "description": ket, "is_private": privat, **kw}

    async def _txn(self, ket):
        async with self.Session() as db:
            return (await db.execute(select(Transaction).where(Transaction.description == ket))).scalars().all()

    # 1. Jenis ruang dari amplop ------------------------------------------------------------------------------
    async def test_jenis_ruang_dari_amplop_bukan_header_atau_body(self):
        palsu = {"ruang_id": str(self.rumah_id), "household_id": str(self.rumah_id)}
        r = await self._req("POST", "/transactions/", self.body(self.op_id, "header keluarga", **palsu),
                            header=self.rumah_id, user=self.me)
        self.assertEqual((r.status_code, r.json().get("kode")), (422, KODE), r.text)
        r = await self._req("POST", "/transactions/batch",
                            {"items": [self.body(self.op_id, "header keluarga", client_ref="h1", **palsu)]},
                            header=self.rumah_id, user=self.me)
        self.assertEqual(r.json()[0]["kode"], KODE, r.text)
        self.assertEqual(await self._txn("header keluarga"), [])
        # Arah sebaliknya: amplop ruang keluarga dengan header ruang usaha tetap boleh privat.
        r = await self._req("POST", "/transactions/", self.body(self.k["env"], "kado header usaha"),
                            header=self.nusa_id, user=self.me)
        self.assertIn(r.status_code, (200, 201), r.text)
        r = await self._req("POST", "/transactions/batch",
                            {"items": [self.body(self.k["env"], "kado header usaha", client_ref="h2")]},
                            header=self.nusa_id, user=self.me)
        self.assertTrue(r.json()[0]["ok"], r.text)
        self.assertEqual([t.is_private for t in await self._txn("kado header usaha")], [True, True])

    # 2. Kirim ulang ------------------------------------------------------------------------------------------
    async def test_kirim_ulang_ref_bertanda_privat_tidak_mengubah_catatan(self):
        r = await self._req("POST", "/transactions/", self.body(self.op_id, "gas elpiji", privat=False,
                                                                client_ref="ulang-1"), user=self.dewi)
        self.assertIn(r.status_code, (200, 201), r.text)
        asli = r.json()["id"]
        r = await self._req("POST", "/transactions/", self.body(self.op_id, "gas elpiji", client_ref="ulang-1"),
                            user=self.dewi)
        self.assertIn(r.status_code, (200, 201), r.text)
        self.assertEqual((r.json()["id"], r.json()["is_private"]), (asli, False))
        r = await self._req("POST", "/transactions/batch",
                            {"items": [self.body(self.op_id, "gas elpiji", client_ref="ulang-1")]}, user=self.dewi)
        self.assertEqual((r.json()[0]["ok"], r.json()[0]["id"]), (True, asli), r.text)
        self.assertEqual([t.is_private for t in await self._txn("gas elpiji")], [False])

    async def test_kirim_ulang_draf_bertanda_privat_tetap_draf_terbuka(self):
        await self._batasan(batas_nominal=10000)
        r = await self._req("POST", "/transactions/", self.body(self.op_id, "kompor", privat=False, client_ref="d-1"),
                            user=self.dewi)
        self.assertEqual(r.status_code, 202, r.text)
        draf_id = r.json()["draf_id"]
        r = await self._req("POST", "/transactions/", self.body(self.op_id, "kompor", client_ref="d-1"), user=self.dewi)
        self.assertEqual((r.status_code, r.json().get("draf_id")), (202, draf_id), r.text)
        r = await self._req("POST", "/transactions/batch",
                            {"items": [self.body(self.op_id, "kompor", client_ref="d-1")]}, user=self.dewi)
        self.assertEqual((r.json()[0]["kode"], r.json()[0]["draf_id"]), ("perlu_persetujuan", draf_id), r.text)
        async with self.Session() as db:
            self.assertEqual([d.is_private for d in (await db.execute(select(RuangDraf))).scalars()], [False])
        r = await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{draf_id}/setujui", user=self.ani)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([t.is_private for t in await self._txn("kompor")], [False])

    # 3. Kotak Struk ------------------------------------------------------------------------------------------
    async def test_bukti_kotak_struk_tidak_terklaim_saat_ditolak(self):
        async with self.Session() as db:
            bukti = ReceiptScan(user_id=self.me.id, household_id=self.rumah_id, status="siap", doc_type="qris",
                                source="web_form", document={"doc_type": "qris"})
            db.add(bukti)
            await db.commit()
            bukti_id = bukti.id
        isi = dict(receipt_item_id=str(bukti_id), client_ref="struk-1")
        r = await self._req("POST", "/transactions/", self.body(self.op_id, "qris toko", **isi), user=self.me)
        self.assertEqual((r.status_code, r.json().get("kode")), (422, KODE), r.text)
        r = await self._req("POST", "/transactions/batch", {"items": [self.body(self.op_id, "qris toko", **isi)]},
                            user=self.me)
        self.assertEqual(r.json()[0]["kode"], KODE, r.text)
        async with self.Session() as db:
            b = await db.get(ReceiptScan, bukti_id)
            self.assertEqual((b.status, b.transaction_ids), ("siap", None))
        self.assertEqual(await self._txn("qris toko"), [])
        # Tanpa tanda privat: bukti yang sama tercatat sekali.
        r = await self._req("POST", "/transactions/", self.body(self.op_id, "qris toko", privat=False, **isi),
                            user=self.me)
        self.assertIn(r.status_code, (200, 201), r.text)
        async with self.Session() as db:
            self.assertEqual((await db.get(ReceiptScan, bukti_id)).status, "tercatat")
        self.assertEqual([t.is_private for t in await self._txn("qris toko")], [False])

    # 4. Temuan R1: transaksi tertunda lama --------------------------------------------------------------------
    async def test_tertunda_lama_privat_di_ruang_usaha_dikonfirmasi_terbuka(self):
        """Tidak ada jalur yang membuat baris tertunda lagi (Pikir-Pikir Fase 0), tetapi `confirm_pending` tetap jalur
        tulis pengeluaran: baris lama bertanda privat di amplop ruang usaha dicatat terbuka; ruang keluarga tetap."""
        lalu = datetime.now(timezone.utc) - timedelta(hours=1)
        async with self.Session() as db:   # satu sesi: SQLite tidak menyimpan zona waktu `confirm_after`
            tertunda = [PendingTransaction(
                envelope_id=env, user_id=self.me.id, amount=D("30000"), description=ket,
                source=TransactionSource.telegram, status=PendingTransactionStatus.pending, cooling_hours=24,
                confirm_after=lalu, expires_at=lalu + timedelta(days=2), is_private=True,
            ) for env, ket in ((self.op_id, "tertunda usaha"), (self.k["env"], "tertunda keluarga"))]
            db.add_all(tertunda)
            await db.commit()
            for p in tertunda:
                self.assertEqual((await confirm_pending(p.id, db)).get("status"), "confirmed")
        self.assertEqual([t.is_private for t in await self._txn("tertunda usaha")], [False])
        self.assertEqual([t.is_private for t in await self._txn("tertunda keluarga")], [True])

    # 5. Temuan R2: urutan pemeriksaan di /batch ---------------------------------------------------------------
    async def test_batch_tidak_membedakan_amplop_pribadi_anggota_lain(self):
        async with self.Session() as db:
            saku = Envelope(household_id=self.nusa_id, name="Uang saku Ani", emoji="👛", budget_amount=D("0"),
                            owner_id=self.ani.id)
            db.add(saku)
            await db.commit()
            saku_id = saku.id
        for user in (self.me, self.dewi):
            hasil = []
            for privat in (True, False):
                r = await self._req("POST", "/transactions/batch",
                                    {"items": [self.body(saku_id, "intip", privat=privat)]}, user=user)
                self.assertEqual(r.status_code, 200, r.text)
                hasil.append({k: v for k, v in r.json()[0].items() if k in ("ok", "error", "kode")})
            self.assertEqual(hasil[0], hasil[1], user.name)
            self.assertEqual(hasil[0]["error"], "Envelope not found")
            # Sama dengan `POST /transactions/`: amplop pribadi orang lain = 404, apa pun tanda privatnya.
            r = await self._req("POST", "/transactions/", self.body(saku_id, "intip"), user=user)
            self.assertEqual(r.status_code, 404, r.text)

    # 6. Temuan S2: lapis kedua kamus ruang lewat route --------------------------------------------------------
    async def test_lapis_kedua_privat_tidak_mengajari_kamus_ruang_lewat_route(self):
        """Lapis pertama (penolakan privat) sengaja dimatikan: jenis ruang yang dibaca `transactions.py` dipalsukan
        menjadi ruang keluarga. Kamus ruang menentukan jenis ruangnya sendiri (`txn_nlp`), jadi yang diuji di sini
        adalah kabel route → `_after_saved(is_private=…)`."""
        with patch("app.api.routes.transactions.ruang_jenis", AsyncMock(return_value=HouseholdType.RUMAH_TANGGA)):
            r = await self._req("POST", "/transactions/", self.body(self.op_id, "rahasia dapur"), user=self.me)
            self.assertIn(r.status_code, (200, 201), r.text)
            r = await self._req("POST", "/transactions/batch",
                                {"items": [self.body(self.op_id, "resep warisan", client_ref="k-1")]}, user=self.me)
            self.assertTrue(r.json()[0]["ok"], r.text)
            # Kontrol: catatan terbuka lewat jalur yang sama mengajari kamus (tesnya tidak lolos karena hook mati).
            r = await self._req("POST", "/transactions/", self.body(self.op_id, "kardus", privat=False), user=self.me)
            self.assertIn(r.status_code, (200, 201), r.text)
        async with self.Session() as db:
            kata = set((await db.execute(select(RuangKamus.keyword).where(
                RuangKamus.household_id == self.nusa_id))).scalars())
        self.assertEqual(kata, {"kardus"})


if __name__ == "__main__":
    unittest.main()
