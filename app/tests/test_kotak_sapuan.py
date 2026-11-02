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


def checks_text(checks: dict) -> str:
    return json.dumps(checks, sort_keys=True, ensure_ascii=False)


def store_problems(e: dict) -> list[str]:
    """Penyimpangan struk belanja dari "tidak berubah" pada satu saklar: jenis, status, cek, rincian, merchant."""
    out = []
    if e["doc_type"] != "struk_belanja":
        out.append(f"doc_type {e['doc_type']}")
    if e["status"] != "berhasil":
        out.append(f"status {e['status']}")
    if e["checks"]:
        out.append(f"cek {checks_text(e['checks'])}")
    if e["unread_proof"] is not False:
        out.append("dianggap bukti bayar")
    if not e["lines"] > 0:
        out.append("tanpa rincian")
    if not e["merchant"]:
        out.append("tanpa merchant")
    return out


def block_problems(e: dict, tags: list[str]) -> list[str]:
    """Pada satu saklar: bukti gagal harus `status_gagal: block`; bukti pending `status_pending: warn` (atau block bila
    juga gagal)."""
    out = []
    checks = e["checks"]
    if "failed" in tags and checks.get("status_gagal") != "block":
        out.append(f"status {e['status']}, cek {checks_text(checks)}")
    if "pending" in tags:
        allowed = ("warn", "block") if "failed" in tags else ("warn",)
        if checks.get("status_pending") not in allowed:
            out.append(f"status {e['status']}, cek {checks_text(checks)}")
    return out


class SweepFixtureTests(unittest.TestCase):
    def test_fixture_shape(self):
        """Sapuan memuat >= 120 daftar dengan id unik dan tag yang dikenal. `known_<item>` hanya pada daftar yang dibaca
        invarian (`store`, `failed`, `pending`), dengan alasan di `note` dan `known` = {saklar: penyimpangan persis}
        untuk saklar yang menyimpang saja."""
        self.assertGreaterEqual(len(SWEEP), 120)
        ids = [e["id"] for e in SWEEP]
        self.assertEqual(len(ids), len(set(ids)))
        for e in SWEEP:
            with self.subTest(e["id"]):
                self.assertTrue(e["lines"] and all(isinstance(x, str) for x in e["lines"]))
                self.assertTrue(e["tags"])
                tags = set(e["tags"])
                for tag in tags:
                    self.assertTrue(tag in TAGS or re.fullmatch(r"known_[a-z0-9_]+", tag), tag)
                # struk yang memang gagal/pending bertag store_void/store_pending, bukan store
                self.assertFalse("store" in tags and {"failed", "pending"} & tags)
                if known(e):
                    self.assertTrue({"store", "failed", "pending"} & tags, "known_* tanpa invarian yang membacanya")
                    self.assertTrue((e.get("note") or "").strip(), "known_* butuh alasan tertulis di `note`")
                    deviations = e.get("known")
                    self.assertIsInstance(deviations, dict)
                    self.assertTrue(deviations and set(deviations) <= set(SWITCHES), deviations)
                    for sw, items in deviations.items():
                        self.assertTrue(items and all(isinstance(x, str) and x for x in items), (sw, items))
                else:
                    self.assertNotIn("known", e)
        for tag in ("store", "store_void", "store_pending", "proof", "failed", "pending", "probe"):
            self.assertTrue(any(tag in e["tags"] for e in SWEEP), tag)


def check_switches(case: unittest.TestCase, entry: dict, got: dict, problems) -> None:
    """Saklar tanpa `known`: invarian penuh (tanpa penyimpangan). Saklar dengan `known`: penyimpangannya harus persis
    yang tertulis — sudah lolos berarti tag `known_*` dihapus, penyimpangan lain berarti perubahan yang harus ditinjau."""
    deviations = entry.get("known") or {}
    for sw in SWITCHES:
        with case.subTest(entry["id"], saklar=sw):
            found = problems(got[sw])
            if sw not in deviations:
                case.assertEqual(found, [])
            elif not found:
                case.fail(f"{entry['id']} {sw}: sudah lolos, hapus {known(entry)} / known.{sw}")
            else:
                case.assertEqual(found, deviations[sw], f"{entry['id']} {sw}: penyimpangan berubah")


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
        rincian dan merchant. `known` (per saklar) = temuan terbuka yang penyimpangannya dipin persis; saklar lain tetap
        diperiksa penuh."""
        for e in SWEEP:
            if "store" in e["tags"]:
                check_switches(self, e, self.got[e["id"]], store_problems)

    async def test_failed_proofs_stay_blocked(self):
        """Setiap `failed`: `status_gagal: block` di kedua saklar; setiap `pending`: `status_pending: warn` (atau block
        bila juga gagal). `known` per saklar seperti di atas."""
        for e in SWEEP:
            if {"failed", "pending"} & set(e["tags"]):
                check_switches(self, e, self.got[e["id"]], lambda got, tags=e["tags"]: block_problems(got, tags))


if __name__ == "__main__":
    unittest.main()
