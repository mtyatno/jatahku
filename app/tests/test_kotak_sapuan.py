import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import json, re, unittest
from pathlib import Path

from app.scripts import kotak_sapuan

FIXTURES = Path(__file__).parent / "fixtures" / "kotak"
LINES_PATH = FIXTURES / "sweep_lines.json"
SNAPSHOT_PATH = FIXTURES / "sweep_snapshot.json"
SWEEP = json.loads(LINES_PATH.read_text(encoding="utf-8"))
TAGS = {"store", "store_void", "store_pending", "proof", "failed", "pending", "probe"}
SWITCHES = ("off", "on")
_BUILT: dict = {}   # satu sapuan untuk semua tes modul ini (sekitar 2 detik)


def known(entry: dict) -> list[str]:
    return [t for t in entry["tags"] if t.startswith("known_")]


def store_problems(got: dict) -> list[str]:
    """Penyimpangan struk belanja dari "tidak berubah": jenis, status, cek, rincian, merchant (per saklar)."""
    out = []
    for sw in SWITCHES:
        e = got[sw]
        if e["doc_type"] != "struk_belanja":
            out.append(f"{sw}: doc_type {e['doc_type']}")
        if e["status"] != "berhasil":
            out.append(f"{sw}: status {e['status']}")
        if e["checks"]:
            out.append(f"{sw}: cek {e['checks']}")
        if e["unread_proof"] is not False:
            out.append(f"{sw}: dianggap bukti bayar")
        if not e["lines"] > 0:
            out.append(f"{sw}: tanpa rincian")
        if not e["merchant"]:
            out.append(f"{sw}: tanpa merchant")
    return out


def block_problems(got: dict, tags: list[str]) -> list[str]:
    """Bukti gagal harus `status_gagal: block`; bukti pending `status_pending: warn` (atau block bila juga gagal)."""
    out = []
    for sw in SWITCHES:
        checks = got[sw]["checks"]
        if "failed" in tags and checks.get("status_gagal") != "block":
            out.append(f"{sw}: status_gagal {checks.get('status_gagal')} (status {got[sw]['status']})")
        if "pending" in tags:
            level = checks.get("status_pending")
            allowed = ("warn", "block") if "failed" in tags else ("warn",)
            if level not in allowed:
                out.append(f"{sw}: status_pending {level} (status {got[sw]['status']})")
    return out


class SweepFixtureTests(unittest.TestCase):
    def test_fixture_shape(self):
        """Sapuan memuat >= 120 daftar dengan id unik dan tag yang dikenal; setiap `known_<item>` punya alasan tertulis."""
        self.assertGreaterEqual(len(SWEEP), 120)
        ids = [e["id"] for e in SWEEP]
        self.assertEqual(len(ids), len(set(ids)))
        for e in SWEEP:
            with self.subTest(e["id"]):
                self.assertTrue(e["lines"] and all(isinstance(x, str) for x in e["lines"]))
                self.assertTrue(e["tags"])
                for tag in e["tags"]:
                    self.assertTrue(tag in TAGS or re.fullmatch(r"known_[a-z0-9]+", tag), tag)
                if known(e):
                    self.assertTrue((e.get("note") or "").strip(), "known_* butuh alasan tertulis di `note`")
        for tag in ("store", "store_void", "store_pending", "proof", "failed", "pending", "probe"):
            self.assertTrue(any(tag in e["tags"] for e in SWEEP), tag)


class SweepTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not _BUILT:
            _BUILT.update(await kotak_sapuan.build(LINES_PATH))
        self.got = _BUILT

    async def test_snapshot_matches(self):
        """Pembaca hari ini == snapshot tersimpan. Perubahan yang disengaja: `python3 -m app.scripts.kotak_sapuan cek`
        (cantumkan bedanya di laporan task), lalu `tulis`."""
        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(sorted(self.got), sorted(snapshot))
        diffs = kotak_sapuan.diff(snapshot, self.got)
        self.assertEqual(diffs, [], "\n".join(diffs[:40]))

    async def test_store_receipts_unchanged_by_sweep(self):
        """Independen dari snapshot: setiap daftar `store`, kedua saklar, tetap struk belanja berhasil tanpa cek, dengan
        rincian dan merchant. `known_<item>` = temuan terbuka (alasan di fixture) yang dilewati; selama tag itu ada,
        daftarnya memang masih menyimpang (tag dihapus saat perbaikannya mendarat)."""
        for e in SWEEP:
            if "store" not in e["tags"]:
                continue
            with self.subTest(e["id"]):
                problems = store_problems(self.got[e["id"]])
                if known(e):
                    self.assertTrue(problems, f"{e['id']}: sudah lolos, hapus {known(e)}")
                else:
                    self.assertEqual(problems, [])

    async def test_failed_proofs_stay_blocked(self):
        """Setiap `failed`: `status_gagal: block` di kedua saklar; setiap `pending`: `status_pending: warn` (atau block
        bila juga gagal). `known_<item>` dilewati seperti di atas."""
        for e in SWEEP:
            if not {"failed", "pending"} & set(e["tags"]):
                continue
            with self.subTest(e["id"]):
                problems = block_problems(self.got[e["id"]], e["tags"])
                if known(e):
                    self.assertTrue(problems, f"{e['id']}: sudah lolos, hapus {known(e)}")
                else:
                    self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
