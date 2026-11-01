"""Siklus household, Task 10: skrip migrasi `app.scripts.siklus_household` (--dry-run / --apply).

Tanpa Postgres: `db_with(...)` / `FakeResult` dari app/tests/fakes.py; household dan user memakai SimpleNamespace; IO di
sekeliling (`heal`, `recompute_history`, `notify_payday_changed`, `household_payday`, `AsyncSessionLocal`, `engine`)
di-patch di modul sumbernya (`app.services.household_cycle`, `app.core.database`): skrip mengimpornya saat dipakai,
supaya `--help` tidak butuh konfigurasi server. `main` memakai `asyncio.run`, jadi tes `main` memakai `TestCase` biasa.
Run: DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret \
     python -m unittest app.tests.test_siklus_household_script -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import contextlib
import dataclasses
import io
import subprocess
import sys
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

from app.models.models import HouseholdRole, HouseholdType
from app.scripts import siklus_household as script
from app.services import household_cycle as hc
from app.tests.fakes import FakeResult, db_with, executed_sql

REPO = Path(__file__).resolve().parents[2]
OLDER_DATE = datetime(2025, 1, 1, tzinfo=timezone.utc)  # `created_at` seperti dari DB: timestamptz (aware)
OWNER_DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)
MEMBER_DATE = datetime(2026, 2, 1, tzinfo=timezone.utc)


class FakeSession:
    """Pengganti `AsyncSessionLocal()`: `async with` menghasilkan `db` tiruan (pola test_household_cycle_change)."""
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def norm(statement: str) -> str:
    """SQL hasil compile berisi newline antar klausa; rapatkan supaya assert tidak bergantung pada tata letak."""
    return " ".join(statement.split())


def household(name="Rumah Budi", payday=None, kind=HouseholdType.RUMAH_TANGGA):
    return SimpleNamespace(id=uuid.uuid4(), name=name, payday_day=payday, type=kind)


def db_row(name, role, payday, created=OWNER_DATE):
    """Baris yang dikembalikan kueri `member_rows`: (role, created_at, user_id, name, payday_day)."""
    return (role, created, uuid.uuid4(), name, payday)


def two_rows(owner_payday, member_payday):
    """`member_rows` untuk Budi (owner) dan Ani (member): paydays yang berbeda membuat household campuran."""
    return [
        db_row("Budi", HouseholdRole.owner, owner_payday),
        db_row("Ani", HouseholdRole.member, member_payday, MEMBER_DATE),
    ]


def member(name, role, payday, created=OWNER_DATE):
    return hc.MemberRow(user_id=uuid.uuid4(), name=name, role=role, created_at=created, payday_day=payday)


def person(name, payday=1):
    """User yang dikembalikan `heal` (yang payday-nya baru disamakan)."""
    return SimpleNamespace(id=uuid.uuid4(), name=name, payday_day=payday)


def surveyed(home, members, target, mixed=False):
    return script.HouseholdSurvey(household=home, members=members, target_payday=target, mixed=mixed)


def periods_result(*created):
    """Hasil `recompute_history`: satu dict per periode (bentuk `rollover.recompute_household`)."""
    return [{"period": f"p{i}", "processed": n, "snapshots_created": n, "errors": []} for i, n in enumerate(created, 1)]


class SurveyTests(unittest.IsolatedAsyncioTestCase):
    async def test_household_survey_fields_follow_the_brief(self):
        self.assertEqual(
            [f.name for f in dataclasses.fields(script.HouseholdSurvey)],
            ["household", "members", "target_payday", "mixed"],
        )

    async def test_survey_marks_mixed(self):
        # Anggota dengan payday 1 dan 25: campuran. Target = payday household yang tersimpan (10), bukan milik anggota.
        home = household(payday=10)
        db = db_with(
            FakeResult(rows=[home]),
            FakeResult(rows=two_rows(1, 25)),
        )
        (item,) = await script.survey(db)
        self.assertIs(item.household, home)
        self.assertIs(item.mixed, True)
        self.assertEqual(item.target_payday, 10)
        self.assertEqual([(m.name, m.payday_day) for m in item.members], [("Budi", 1), ("Ani", 25)])

    async def test_survey_target_of_unmigrated_household_is_the_owners_payday_and_nothing_is_written(self):
        # households.payday_day NULL: target diturunkan (owner 25 menang atas member yang lebih tua, payday 1), tetapi
        # dry-run tidak mengisinya: tidak assign, flush, commit, maupun add.
        home = household(payday=None)
        db = db_with(
            FakeResult(rows=[home]),
            FakeResult(rows=[
                db_row("Ani", HouseholdRole.member, 1, OLDER_DATE),
                db_row("Budi", HouseholdRole.owner, 25, OWNER_DATE),
            ]),
        )
        (item,) = await script.survey(db)
        self.assertIs(item.mixed, True)
        self.assertEqual(item.target_payday, 25)
        self.assertIsNone(home.payday_day)
        db.flush.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.add.assert_not_called()

    async def test_survey_same_payday_is_not_mixed(self):
        home = household(payday=25)
        db = db_with(
            FakeResult(rows=[home]),
            FakeResult(rows=two_rows(25, 25)),
        )
        (item,) = await script.survey(db)
        self.assertIs(item.mixed, False)
        self.assertEqual(item.target_payday, 25)

    async def test_survey_business_space_is_never_mixed(self):
        # Spec bagian 10: hanya ruang keluarga yang mencerminkan payday ke user. Anggota ruang usaha memang boleh punya
        # payday pribadi berbeda (itu siklus ruang keluarga mereka), jadi bukan campuran; `heal` pun melewatinya.
        usaha = household("Toko Budi", payday=5, kind=HouseholdType.USAHA)
        keluarga = household("Rumah Budi", payday=5)
        people = [db_row("Budi", HouseholdRole.owner, 1), db_row("Ani", HouseholdRole.member, 25, MEMBER_DATE)]
        db = db_with(FakeResult(rows=[usaha, keluarga]), FakeResult(rows=people), FakeResult(rows=people))
        usaha_item, keluarga_item = await script.survey(db)
        self.assertIs(usaha_item.mixed, False)
        self.assertEqual(usaha_item.target_payday, 5)
        self.assertIs(keluarga_item.mixed, True)

    async def test_survey_skips_households_without_members(self):
        db = db_with(FakeResult(rows=[]))
        self.assertEqual(await script.survey(db), [])
        (statement,) = executed_sql(db)  # tanpa household, tidak ada kueri anggota
        self.assertIn("FROM households", norm(statement))
        self.assertIn(
            "households.id IN (SELECT household_members.household_id FROM household_members)", norm(statement)
        )
        self.assertIn("ORDER BY households.created_at", norm(statement))  # urutan tetap: daftar dry-run stabil

    async def test_survey_loads_members_once_per_household_in_order(self):
        first, second = household("Rumah Budi", 25), household("Rumah Ani", 10)
        db = db_with(
            FakeResult(rows=[first, second]),
            FakeResult(rows=[db_row("Budi", HouseholdRole.owner, 25)]),
            FakeResult(rows=[
                db_row("Ani", HouseholdRole.owner, 10), db_row("Citra", HouseholdRole.member, 10, MEMBER_DATE),
            ]),
        )
        items = await script.survey(db)
        self.assertEqual([i.household for i in items], [first, second])
        self.assertEqual([len(i.members) for i in items], [1, 2])
        statements = [c.args[0] for c in db.execute.call_args_list]
        self.assertEqual(len(statements), 3)  # household, lalu satu kueri anggota per household
        for statement, home in zip(statements[1:], (first, second)):
            self.assertIn(
                "FROM household_members JOIN users ON users.id = household_members.user_id", norm(str(statement))
            )
            self.assertEqual(list(statement.compile().params.values()), [home.id])  # id terikat: household-nya sendiri


class FormatSurveyTests(unittest.TestCase):
    def test_one_line_per_household_and_exact_summary_line(self):
        mixed_home, plain_home = household("Rumah Budi", 25), household("Rumah Ani", 10)
        mixed = surveyed(
            mixed_home,
            [member("Budi", HouseholdRole.owner, 1), member("Ani", HouseholdRole.member, 25, MEMBER_DATE)],
            target=25, mixed=True,
        )
        plain = surveyed(plain_home, [member("Ani", HouseholdRole.owner, 10)], target=10)
        lines = script.format_survey([mixed, plain]).split("\n")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[-1], "2 household, 1 campuran")
        for part in (str(mixed_home.id), "Rumah Budi", "2 anggota", "Budi (owner)=1", "Ani (member)=25", "target 25",
                     "CAMPURAN"):
            self.assertIn(part, lines[0])
        for part in (str(plain_home.id), "Rumah Ani", "1 anggota", "Ani (owner)=10", "target 10"):
            self.assertIn(part, lines[1])
        self.assertNotIn("CAMPURAN", lines[1])

    def test_summary_line_for_an_empty_survey(self):
        self.assertEqual(script.format_survey([]), "0 household, 0 campuran")

    def test_roles_print_as_their_value_for_enums_and_strings(self):
        # `str(HouseholdRole.owner)` adalah "HouseholdRole.owner": yang dicetak nilainya (AGENTS.md: enum vs string).
        item = surveyed(
            household(payday=1),
            [member("Budi", HouseholdRole.owner, 1), member("Ani", "member", 1, MEMBER_DATE)],
            target=1,
        )
        line = script.format_survey([item]).split("\n")[0]
        self.assertIn("Budi (owner)=1", line)
        self.assertIn("Ani (member)=1", line)
        self.assertNotIn("HouseholdRole", line)

    def test_business_space_is_marked_so_a_missing_campuran_is_not_a_surprise(self):
        item = surveyed(
            household("Toko Budi", 5, kind=HouseholdType.USAHA),
            [member("Budi", HouseholdRole.owner, 1), member("Ani", HouseholdRole.member, 25, MEMBER_DATE)],
            target=5,
        )
        line = script.format_survey([item]).split("\n")[0]
        self.assertIn("[usaha]", line)
        self.assertNotIn("CAMPURAN", line)
        family = surveyed(household(payday=5), [member("Budi", HouseholdRole.owner, 1)], target=5)
        self.assertNotIn("[", script.format_survey([family]).split("\n")[0])

    def test_names_from_users_cannot_break_the_listing(self):
        # Nama rumah dan anggota diketik user: baris baru memecah "satu baris per household", dan kode kontrol
        # (escape terminal) akan sampai ke terminal admin. Semuanya dirapikan jadi spasi.
        item = surveyed(
            household("Rumah\nPalsu \x1b[2J", 1),
            [member("Bud\ri\x07", HouseholdRole.owner, 1), member("An i", HouseholdRole.member, 1, MEMBER_DATE)],
            target=1,
        )
        text = script.format_survey([item])
        self.assertEqual(len(text.splitlines()), 2)  # satu baris household + ringkasan
        self.assertEqual(text.splitlines()[-1], "1 household, 0 campuran")
        self.assertTrue(all(ch.isprintable() or ch == "\n" for ch in text))
        self.assertIn("Rumah Palsu [2J", text)


class ApplyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Semua IO di sekitar `apply` diganti; tiap tes memeriksa panggilannya. `household_payday` asli: household yang
        # sudah punya payday kembali tanpa kueri, yang NULL diisi dari anggota survei.
        self.heal = AsyncMock(return_value=[])
        self.recompute = AsyncMock(return_value=[])
        self.notify = AsyncMock(return_value=0)
        self.enterContext(patch.object(hc, "heal", self.heal))
        self.enterContext(patch.object(hc, "recompute_history", self.recompute))
        self.enterContext(patch.object(hc, "notify_payday_changed", self.notify))

    async def test_apply_heals_recomputes_and_notifies_changed_only(self):
        first, second = household("Rumah Budi", 25), household("Rumah Ani", 10)
        budi = person("Budi", 1)
        self.heal.side_effect = [[budi], []]  # Budi disamakan di rumah pertama; rumah kedua sudah rapi
        self.recompute.side_effect = [periods_result(2, 1), periods_result(4)]
        self.notify.return_value = 1
        db = db_with()
        items = [
            surveyed(
                first, [member("Budi", HouseholdRole.owner, 25), member("Ani", HouseholdRole.member, 1)], 25, mixed=True
            ),
            surveyed(second, [member("Ani", HouseholdRole.owner, 10)], 10),
        ]
        result = await script.apply(db, items, 12)
        self.assertEqual(self.heal.await_args_list, [call(db, first), call(db, second)])
        self.assertEqual(self.recompute.await_args_list, [call(first.id, 12), call(second.id, 12)])
        # `periods` di notifikasi = periode yang benar-benar dihitung ulang household itu (2), bukan yang diminta (12).
        self.notify.assert_awaited_once_with([budi], household_name="Rumah Budi", day=25, changed_by=None, periods=2)
        self.assertEqual(result, {"households": 2, "mixed": 1, "snapshots": 7, "notified": 1, "errors": 0})

    async def test_apply_passes_the_minimum_to_recompute_and_the_actual_count_to_the_notification(self):
        # Ruling R18: --periods hanya batas bawah; recompute mundur sampai aktivitas pertama (di sini 7 periode), dan
        # notifikasi menyebut jumlah yang benar-benar dihitung ulang.
        home = household("Rumah Budi", 25)
        self.heal.return_value = [person("Budi", 1)]
        self.recompute.return_value = periods_result(1, 1, 1, 1, 1, 1, 1)
        await script.apply(db_with(), [surveyed(home, [member("Budi", HouseholdRole.owner, 25)], 25)], 6)
        self.recompute.assert_awaited_once_with(home.id, 6)
        self.assertEqual(self.notify.await_args.kwargs["periods"], 7)

    async def test_apply_twice_is_idempotent(self):
        home = household("Rumah Budi", 25)
        budi = person("Budi", 1)
        people = [member("Budi", HouseholdRole.owner, 25), member("Ani", HouseholdRole.member, 1)]
        items = [surveyed(home, people, 25, mixed=True)]
        db = db_with()
        self.heal.side_effect = [[budi], []]  # kali pertama menyamakan Budi; kali kedua tidak ada yang berubah lagi
        self.recompute.return_value = periods_result(3)
        self.notify.return_value = 1
        first = await script.apply(db, items, 12)
        self.notify.assert_awaited_once()
        self.notify.reset_mock()
        second = await script.apply(db, items, 12)
        self.notify.assert_not_awaited()  # tidak ada notifikasi kedua
        self.assertEqual((first["notified"], second["notified"]), (1, 0))
        self.assertEqual(self.recompute.await_count, 2)  # riwayat tetap dihitung ulang (deterministik, aman diulang)
        self.assertEqual(second, {"households": 1, "mixed": 1, "snapshots": 3, "notified": 0, "errors": 0})

    async def test_apply_commits_the_session_before_every_recompute(self):
        # Kontrak `recompute_history` (docstring `household_cycle`, ruling R7): ia membaca state yang sudah tersimpan
        # lewat sesinya sendiri, sedangkan `household_payday` hanya flush pengisian NULL. Maka `apply` commit sendiri
        # untuk TIAP household sebelum recompute. Urutan per household (ruling R17): payday, commit, recompute, lalu
        # `heal` dan notifikasi: recompute hanya membaca `households.payday_day`, jadi cermin anggota boleh disamakan
        # sesudahnya, dan pesan "Riwayat ... dihitung ulang" benar saat dikirim.
        null_home, set_home = household("Rumah Budi", None), household("Rumah Ani", 10)
        items = [
            surveyed(null_home, [member("Budi", HouseholdRole.owner, 25)], 25),
            surveyed(set_home, [member("Ani", HouseholdRole.owner, 10)], 10),
        ]
        names = {null_home.id: null_home.name, set_home.id: set_home.name}
        events, filled_at_commit = [], []
        db = db_with()

        def flushed():
            events.append("flush")

        async def committed():
            events.append("commit")
            filled_at_commit.append(null_home.payday_day)

        async def healed(session, home):
            events.append(f"heal:{home.name}")
            return [person("Budi", 1)] if home is null_home else []

        async def recomputed(household_id, periods):
            events.append(f"recompute:{names[household_id]}")
            return periods_result(1)

        async def notified(users, *, household_name, **kwargs):
            events.append(f"notify:{household_name}")
            return len(users)

        db.flush.side_effect = flushed
        db.commit.side_effect = committed
        self.heal.side_effect = healed
        self.recompute.side_effect = recomputed
        self.notify.side_effect = notified
        await script.apply(db, items, 12)
        self.assertEqual(events, [
            "flush", "commit", "recompute:Rumah Budi", "heal:Rumah Budi", "notify:Rumah Budi",  # NULL diisi, di-flush
            "commit", "recompute:Rumah Ani", "heal:Rumah Ani",  # payday sudah terisi: tanpa flush, heal tanpa perubahan
        ])
        self.assertEqual(filled_at_commit[0], 25)  # pengisian NULL sudah terjadi saat commit pertama
        db.execute.assert_not_called()  # anggota survei dipakai ulang: tidak ada kueri anggota kedua
        self.assertEqual(self.notify.await_args.kwargs["day"], 25)  # tanggal yang diisi dipakai di notifikasi

    async def test_failed_recompute_leaves_the_members_for_the_rerun_to_heal_and_notify(self):
        # Ruling R17: `heal` dan notifikasi SESUDAH recompute. Recompute yang gagal tidak boleh sudah menyamakan
        # anggota: `heal` run ulang hanya menemukan anggota yang masih menyimpang, jadi yang sudah disamakan tidak
        # pernah diberi tahu. Pesan skrip ("Riwayat ... dihitung ulang") juga hanya benar sesudah recompute berhasil.
        home = household("Rumah Budi", 25)
        budi = person("Budi", 1)
        people = [member("Budi", HouseholdRole.owner, 25), member("Ani", HouseholdRole.member, 1)]
        item = surveyed(home, people, 25, mixed=True)
        db = db_with()
        self.recompute.side_effect = [RuntimeError("db mati"), periods_result(3)]
        self.heal.return_value = [budi]
        self.notify.return_value = 1
        with self.assertRaisesRegex(RuntimeError, "db mati"):
            await script.apply(db, [item], 12)
        self.heal.assert_not_awaited()  # anggota belum disamakan: run ulang masih menemukan mereka
        self.notify.assert_not_awaited()
        db.commit.assert_awaited_once()  # payday household sudah tersimpan sebelum recompute (kontrak R7)

        result = await script.apply(db, [item], 12)  # run ulang: recompute kini berhasil (satu periode)
        self.heal.assert_awaited_once_with(db, home)
        self.notify.assert_awaited_once_with([budi], household_name="Rumah Budi", day=25, changed_by=None, periods=1)
        self.assertEqual(result, {"households": 1, "mixed": 1, "snapshots": 3, "notified": 1, "errors": 0})

    async def test_apply_counts_only_surveyed_mixed_households(self):
        items = [
            surveyed(household("A", 1), [member("Budi", HouseholdRole.owner, 1)], 1, mixed=True),
            surveyed(household("B", 2), [member("Ani", HouseholdRole.owner, 2)], 2, mixed=False),
            surveyed(household("C", 3), [member("Citra", HouseholdRole.owner, 3)], 3, mixed=True),
        ]
        result = await script.apply(db_with(), items, 12)
        self.assertEqual(result, {"households": 3, "mixed": 2, "snapshots": 0, "notified": 0, "errors": 0})

    async def test_apply_with_nothing_surveyed_does_nothing(self):
        db = db_with()
        self.assertEqual(
            await script.apply(db, [], 12), {"households": 0, "mixed": 0, "snapshots": 0, "notified": 0, "errors": 0}
        )
        db.commit.assert_not_awaited()
        self.heal.assert_not_awaited()
        self.recompute.assert_not_awaited()

    async def test_apply_counts_per_period_errors_of_all_households(self):
        # Error per amplop di dalam periode tidak melempar (recompute_history hanya mencatatnya): skrip menjumlahkannya
        # supaya bisa keluar dengan kode 1. Household berikutnya tetap diproses.
        first, second = household("Rumah Budi", 25), household("Rumah Ani", 10)
        self.recompute.side_effect = [
            [
                {"period": "p1", "processed": 2, "snapshots_created": 1, "errors": ["Makan: boom"]},
                {"period": "p2", "processed": 2, "snapshots_created": 2, "errors": []},
            ],
            [{"period": "p1", "processed": 3, "snapshots_created": 1, "errors": ["Listrik: x", "Air: y"]}],
        ]
        items = [
            surveyed(first, [member("Budi", HouseholdRole.owner, 25)], 25),
            surveyed(second, [member("Ani", HouseholdRole.owner, 10)], 10),
        ]
        result = await script.apply(db_with(), items, 12)
        self.assertEqual(result, {"households": 2, "mixed": 0, "snapshots": 4, "notified": 0, "errors": 3})
        self.assertEqual(self.heal.await_count, 2)


class MainTests(unittest.TestCase):
    def run_main(self, argv, db):
        engine = SimpleNamespace(dispose=AsyncMock())
        out, err = io.StringIO(), io.StringIO()
        with patch("app.core.database.AsyncSessionLocal", new=lambda: FakeSession(db)), \
                patch("app.core.database.engine", new=engine), redirect_stdout(out), redirect_stderr(err):
            code = script.main(argv)
        return code, out.getvalue(), engine

    def parse_fails(self, argv):
        """`main(argv)` yang ditolak argparse: (kode keluar, stderr). Sesi tidak boleh dibuka sama sekali."""
        err = io.StringIO()
        with patch("app.core.database.AsyncSessionLocal", side_effect=AssertionError("sesi dibuka")), \
                redirect_stdout(io.StringIO()), redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            script.main(argv)
        return raised.exception.code, err.getvalue()

    @contextlib.contextmanager
    def collaborators(self, *names):
        """Yang menulis atau mengirim di-patch (`names`; bawaan semuanya), dikembalikan sebagai {nama: AsyncMock}."""
        names = names or ("heal", "recompute_history", "notify_payday_changed", "household_payday")
        with contextlib.ExitStack() as stack:
            mocks = {name: AsyncMock() for name in names}
            for name, mock in mocks.items():
                stack.enter_context(patch.object(hc, name, mock))
            yield mocks

    def test_dry_run_writes_nothing(self):
        for argv in ([], ["--dry-run"]):
            with self.subTest(argv=argv), self.collaborators() as mocks:
                home = household("Rumah Budi", None)  # NULL: jalur tulis apa pun akan mengisinya
                db = db_with(
                    FakeResult(rows=[home]),
                    FakeResult(rows=two_rows(25, 1)),
                )
                apply = AsyncMock()
                with patch.object(script, "apply", apply):
                    code, out, engine = self.run_main(argv, db)
                self.assertEqual(code, 0)
                apply.assert_not_awaited()
                for name, mock in mocks.items():
                    with self.subTest(collaborator=name):
                        mock.assert_not_awaited()
                db.commit.assert_not_awaited()
                db.flush.assert_not_awaited()
                db.add.assert_not_called()
                self.assertIsNone(home.payday_day)
                self.assertIn(str(home.id), out)
                self.assertIn("Rumah Budi", out)
                self.assertIn("CAMPURAN", out)
                self.assertIn("1 household, 1 campuran", out.splitlines())
                self.assertIn("Dry-run", out)
                engine.dispose.assert_awaited_once()

    def test_apply_runs_survey_then_apply_and_prints_the_summary(self):
        # `survey` dan `apply` asli, `household_payday` asli (household sudah punya payday: tanpa kueri); yang menulis
        # atau mengirim di-patch.
        home = household("Rumah Budi", 25)
        budi = person("Budi", 1)
        db = db_with(
            FakeResult(rows=[home]),
            FakeResult(rows=two_rows(25, 1)),
        )
        with self.collaborators("heal", "recompute_history", "notify_payday_changed") as mocks:
            mocks["heal"].return_value = [budi]
            mocks["recompute_history"].return_value = periods_result(2, 1)
            mocks["notify_payday_changed"].return_value = 1
            code, out, engine = self.run_main(["--apply"], db)
        self.assertEqual(code, 0)
        mocks["heal"].assert_awaited_once_with(db, home)
        mocks["recompute_history"].assert_awaited_once_with(home.id, 12)
        mocks["notify_payday_changed"].assert_awaited_once_with(
            [budi], household_name="Rumah Budi", day=25, changed_by=None, periods=2,
        )
        db.commit.assert_awaited()
        lines = out.splitlines()
        self.assertIn("1 household, 1 campuran", lines)  # daftar survei dicetak lebih dulu
        self.assertEqual(
            lines[-1],
            "Selesai: 1 household diproses (1 campuran), 3 snapshot ditulis, 1 anggota diberi tahu, 0 error.",
        )
        self.assertNotIn("Dry-run", out)
        engine.dispose.assert_awaited_once()

    def test_periods_option_reaches_apply(self):
        db = db_with()
        survey = AsyncMock(return_value=[])
        apply = AsyncMock(return_value={"households": 0, "mixed": 0, "snapshots": 0, "notified": 0, "errors": 0})
        for argv, expected in ((["--apply"], 12), (["--apply", "--periods", "6"], 6)):
            with self.subTest(argv=argv):
                apply.reset_mock()
                with patch.object(script, "survey", survey), patch.object(script, "apply", apply):
                    code, _, _ = self.run_main(argv, db)
                self.assertEqual(code, 0)
                apply.assert_awaited_once_with(db, [], expected)

    def test_apply_exits_1_and_prints_the_error_count_when_periods_had_errors(self):
        # Error per amplop hanya tercatat di log (`jatahku.household_cycle`, mudah terlewat): baris terakhir menyebut
        # jumlahnya dan kode keluar 1, supaya operator tahu run ini belum bersih.
        home = household("Rumah Budi", 25)
        db = db_with(FakeResult(rows=[home]), FakeResult(rows=two_rows(25, 25)))
        failed = [{"period": "p1", "processed": 3, "snapshots_created": 1, "errors": ["Makan: boom", "Air: x"]}]
        with self.collaborators("heal", "recompute_history", "notify_payday_changed") as mocks:
            mocks["heal"].return_value = []
            mocks["recompute_history"].return_value = failed
            code, out, engine = self.run_main(["--apply"], db)
        self.assertEqual(code, 1)
        self.assertEqual(
            out.splitlines()[-1],
            "Selesai: 1 household diproses (0 campuran), 1 snapshot ditulis, 0 anggota diberi tahu, 2 error.",
        )
        engine.dispose.assert_awaited_once()

    def test_help_names_the_apply_order_and_that_periods_is_a_minimum(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            script.main(["--help"])
        text = " ".join(out.getvalue().split())  # argparse membungkus bantuan argumen sesuai lebar terminal
        self.assertIn("household_payday → commit → recompute_history → heal → notifikasi", text)
        self.assertIn("MINIMAL", text)
        self.assertIn("aktivitas pertama", text)
        self.assertIn("hari yang sama", text)  # langkah --apply: hari merge, sebelum job 00:05 berikutnya

    def test_rejects_bad_arguments_before_opening_a_session(self):
        bad = (["--apply", "--dry-run"], ["--periods", "0"], ["--periods", "-3"], ["--periods", "abc"], ["--bogus"])
        for argv in bad:
            with self.subTest(argv=argv):
                code, stderr = self.parse_fails(argv)
                self.assertEqual(code, 2)
                self.assertIn("usage:", stderr)

    def test_engine_is_disposed_even_when_the_run_fails(self):
        # Pool asyncpg terikat ke event loop `asyncio.run`: ditutup di loop yang sama, juga saat gagal di tengah jalan.
        engine = SimpleNamespace(dispose=AsyncMock())
        boom = AsyncMock(side_effect=RuntimeError("db mati"))
        with patch("app.core.database.AsyncSessionLocal", new=lambda: FakeSession(db_with())), \
                patch("app.core.database.engine", new=engine), patch.object(script, "survey", boom), \
                redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "db mati"):
            script.main(["--apply"])
        engine.dispose.assert_awaited_once()

    def test_help_states_what_it_does_and_the_process_caveat(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            script.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        text = out.getvalue()
        for part in ("--dry-run", "--apply", "--periods", "jam sepi", "00:05", "proses terpisah", "household_lock"):
            self.assertIn(part, text)


class WithoutServerConfigTests(unittest.TestCase):
    """`--help` dan argumen salah tidak boleh butuh konfigurasi server, dan skrip tidak boleh mengarang nilainya
    (tidak seperti kotak_corpus, yang tidak membuka database): `Settings` memberi prioritas pada variabel lingkungan
    di atas /opt/jatahku/.env, jadi nilai bawaan karangan akan menimpa DATABASE_URL asli di VPS."""

    def run_python(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "JWT_SECRET")}
        return subprocess.run(
            [sys.executable, *args], cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
        )

    def test_help_works_without_database_settings(self):
        proc = self.run_python("-m", "app.scripts.siklus_household", "--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--apply", proc.stdout)
        self.assertIn("00:05", proc.stdout)

    def test_importing_the_script_does_not_invent_settings(self):
        code = (
            "import os\n"
            "from app.scripts import siklus_household\n"
            "print(os.environ.get('DATABASE_URL'), os.environ.get('JWT_SECRET'))\n"
        )
        proc = self.run_python("-c", code)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "None None")


if __name__ == "__main__":
    unittest.main()
