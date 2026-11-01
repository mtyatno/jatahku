"""Siklus household, Task 6: `household_cycle` satu-satunya penulis `payday_day`.

Atribut `payday_day` (user maupun household) hanya di-assign di app/services/household_cycle.py, dan SQL `SET payday_day`
hanya ada di app/services/household_cycle_schema.py (backfill). Jalur lain mengubah lewat `set_household_payday` /
`adopt_household_payday` dan membaca lewat `household_payday` / `payday_context`, supaya cermin `users.payday_day` tidak
menyimpang dari `households.payday_day`. Tes ini memindai kode aplikasi (bukan app/tests/) dan gagal dengan file:baris
bila ada penulis lain.
Run: python -m unittest app.tests.test_household_cycle_sole_writer -v
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "app"

# Assignment atribut (`user.payday_day = 5`). `==`, `>=`, argumen kata kunci `payday_day=5` dan deklarasi kolom tidak ikut.
ATTRIBUTE_WRITE = re.compile(r"\.payday_day\s*=(?!=)")
# SQL pengisi (`UPDATE ... SET payday_day = ...`), tanpa membedakan huruf besar/kecil.
SQL_WRITE = re.compile(r"(?i)\bset\s+payday_day\b")

ALLOWED_ATTRIBUTE_WRITERS = {"app/services/household_cycle.py"}
ALLOWED_SQL_WRITERS = {"app/services/household_cycle_schema.py"}


def application_sources():
    """(path relatif repo bergaya POSIX, isi) tiap file .py di app/ selain app/tests/."""
    for path in sorted(APP.rglob("*.py")):
        relative = path.relative_to(REPO)
        if relative.parts[:2] == ("app", "tests"):
            continue
        yield relative.as_posix(), path.read_text(encoding="utf-8")


def matches(pattern):
    """Tiap baris yang cocok dengan `pattern` sebagai (file, nomor baris, teks baris)."""
    found = []
    for file, text in application_sources():
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                found.append((file, number, line.strip()))
    return found


class SoleWriterTests(unittest.TestCase):
    def assert_only_in(self, pattern, allowed, what):
        stray = [f"{file}:{number}: {line}" for file, number, line in matches(pattern) if file not in allowed]
        if stray:
            self.fail(
                f"{what} di luar {', '.join(sorted(allowed))}; ubah lewat household_cycle:\n  " + "\n  ".join(stray)
            )

    def test_household_cycle_sole_writer(self):
        self.assert_only_in(ATTRIBUTE_WRITE, ALLOWED_ATTRIBUTE_WRITERS, "assignment atribut payday_day")
        self.assert_only_in(SQL_WRITE, ALLOWED_SQL_WRITERS, "SQL SET payday_day")


class ScannerSelfCheckTests(unittest.TestCase):
    """Penjaga supaya tes di atas tidak lulus kosong: pemindai harus benar-benar membaca kode aplikasi, dan pola harus
    mengenali penulis yang sah serta membedakan assignment dari pembacaan."""

    def test_scans_application_code_but_not_tests(self):
        files = {file for file, _ in application_sources()}
        self.assertIn("app/services/household_cycle.py", files)
        self.assertIn("app/api/routes/user_settings.py", files)
        self.assertEqual([f for f in files if f.startswith("app/tests/")], [])

    def test_patterns_see_the_allowed_writers(self):
        self.assertTrue([m for m in matches(ATTRIBUTE_WRITE) if m[0] in ALLOWED_ATTRIBUTE_WRITERS])
        self.assertTrue([m for m in matches(SQL_WRITE) if m[0] in ALLOWED_SQL_WRITERS])

    def test_attribute_pattern_separates_writes_from_reads(self):
        for line in ("user.payday_day = 5", "household.payday_day=day", "u.payday_day  =  x"):
            with self.subTest(write=line):
                self.assertTrue(ATTRIBUTE_WRITE.search(line))
        for line in (
            "if user.payday_day == 5:", "user.payday_day >= 1", "user.payday_day != 3", "User(payday_day=5)",
            "payday_day = Column(Integer)", "x = user.payday_day",
        ):
            with self.subTest(read=line):
                self.assertIsNone(ATTRIBUTE_WRITE.search(line))

    def test_sql_pattern_matches_set_only(self):
        for line in ("UPDATE households h SET payday_day = sub.payday_day", "update t set   PAYDAY_DAY = 1"):
            with self.subTest(write=line):
                self.assertTrue(SQL_WRITE.search(line))
        for line in ("SELECT payday_day FROM users", "reset payday_day", "SET payday_day_x = 1"):
            with self.subTest(read=line):
                self.assertIsNone(SQL_WRITE.search(line))


if __name__ == "__main__":
    unittest.main()
