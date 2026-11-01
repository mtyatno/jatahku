"""Siklus household, Task 9: job snapshot harian per household (`scheduler.payday_snapshot_job`) dan fungsi murni
`household_runs`.

Tanpa Postgres: `db_with(...)` / `FakeResult` dari app/tests/fakes.py; household memakai SimpleNamespace. IO di
sekeliling di-patch di tempat namanya terikat: `scheduler.create_monthly_snapshots` dan `scheduler.date` (impor tingkat
modul), sedangkan nama yang diimpor di dalam fungsi job di-patch pada modul sumbernya
(`app.core.database.AsyncSessionLocal`, `household_cycle.household_payday`, `household_cycle.heal`,
`household_cycle.current_payday`). `current_payday` (bacaan tanggal di dalam kunci, R16) membaca `self.stored`, kamus
yang meniru `households.payday_day` dan yang boleh diubah tes selagi job berjalan. Kunci household terikat ke event
loop tempat ia pertama kali diperebutkan, jadi tiap tes yang berebut kunci memakai id household baru.
Run: python -m unittest app.tests.test_scheduler_household_runs -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import unittest
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

from app.services import household_cycle, scheduler
from app.tests.fakes import FakeResult, db_with, executed_sql, fixed_date

TODAY = date(2026, 10, 31)
# Tiga periode tertutup terakhir pada TODAY, oldest-first: payday 1 = bulan kalender, payday 25 = tanggal 25 → 24.
PERIODS_PAYDAY_1 = [
    (date(2026, 7, 1), date(2026, 7, 31)),
    (date(2026, 8, 1), date(2026, 8, 31)),
    (date(2026, 9, 1), date(2026, 9, 30)),
]
PERIODS_PAYDAY_25 = [
    (date(2026, 7, 25), date(2026, 8, 24)),
    (date(2026, 8, 25), date(2026, 9, 24)),
    (date(2026, 9, 25), date(2026, 10, 24)),
]
# 10 Nov 2026: payday 25 masih di periode yang mulai 25 Okt (jadi PERIODS_PAYDAY_25 berlaku juga hari ini), sedangkan
# payday 1 sudah menutup Oktober: kunci snapshot 2026-10 adalah periode BERJALAN menurut payday 25.
RACE_DAY = date(2026, 11, 10)
PERIODS_PAYDAY_1_ON_RACE_DAY = [
    (date(2026, 8, 1), date(2026, 8, 31)),
    (date(2026, 9, 1), date(2026, 9, 30)),
    (date(2026, 10, 1), date(2026, 10, 31)),
]
NOTHING_CREATED = {"processed": 2, "snapshots_created": 0, "errors": []}


def norm(statement: str) -> str:
    """SQL hasil compile berisi newline antar klausa; rapatkan supaya assert tidak bergantung pada tata letak."""
    return " ".join(statement.split())


def make_household():
    """Household dari kueri job. Tanggalnya tidak dibaca dari objek ini: job memintanya lewat `household_payday`."""
    return SimpleNamespace(id=uuid.uuid4(), name="Rumah", payday_day=None)


class HouseholdRunsTests(unittest.TestCase):
    def test_household_runs_one_window_per_household(self):
        h1, h2 = uuid.uuid4(), uuid.uuid4()
        runs = scheduler.household_runs([(h1, 1), (h2, 25)], TODAY, 3)
        self.assertEqual(runs, [(h1, 1, PERIODS_PAYDAY_1), (h2, 25, PERIODS_PAYDAY_25)])

    def test_household_runs_keeps_input_order(self):
        # Urutan input bukan urutan tanggal gajian maupun id: hasilnya mengikuti input apa adanya.
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        runs = scheduler.household_runs([(b, 25), (a, 1), (c, 25)], TODAY, 1)
        self.assertEqual([run[0] for run in runs], [b, a, c])
        self.assertEqual(runs[0][2], [PERIODS_PAYDAY_25[-1]])
        self.assertEqual(runs[1][2], [PERIODS_PAYDAY_1[-1]])
        self.assertEqual(runs[2][2], runs[0][2])  # tanggal gajian sama → jendela sama

    def test_household_runs_edges(self):
        h = uuid.uuid4()
        self.assertEqual(scheduler.household_runs([], TODAY, 3), [])
        self.assertEqual(scheduler.household_runs([(h, 1)], TODAY, 0), [(h, 1, [])])


class FakeSession:
    """Pengganti `AsyncSessionLocal()`: `async with` menghasilkan `db` tiruan dan memanggil `on_close` saat ditutup."""

    def __init__(self, db, on_close=None):
        self.db = db
        self.on_close = on_close

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        if self.on_close:
            self.on_close()
        return False


class JobTestCase(unittest.IsolatedAsyncioTestCase):
    """Dasar tes job. Semua IO tiruan (`AsyncMock`) dan tidak pernah menunda, jadi satu-satunya hal yang bisa
    membuat job menunggu adalah kunci household."""

    def setup_job(self, households, *, payday, fresh=None, heal=None, create=None, on_close=None, today=TODAY):
        """`payday`/`heal`/`create`: `side_effect` (daftar atau fungsi) untuk `household_payday` (bacaan tahap pertama,
        satu sesi), `heal`, `create_monthly_snapshots`; `heal` bawaannya tidak memperbaiki apa pun, `create` bawaannya
        tidak membuat apa pun.

        `current_payday` (bacaan di dalam kunci, R16) mengembalikan `self.stored[id]`. Bawaannya sama dengan bacaan
        tahap pertama; `fresh` ({id household: tanggal atau None}) menggantinya per household (None = household sudah
        dihapus), dan tes boleh mengubah `self.stored` selagi job berjalan untuk meniru perubahan tanggal yang
        di-commit. `self.read_under_lock` mencatat, untuk tiap bacaan itu, apakah kunci household-nya dipegang."""
        self.db = db_with(FakeResult(rows=households))
        self.household_payday = AsyncMock(side_effect=payday)
        self.heal = AsyncMock(return_value=[]) if heal is None else AsyncMock(side_effect=heal)
        self.create = AsyncMock(return_value=NOTHING_CREATED) if create is None else AsyncMock(side_effect=create)
        self.stored = dict(fresh or {})
        self.read_under_lock = []

        async def first_read(db, household):
            value = await self.household_payday(db, household)
            self.stored.setdefault(household.id, value)
            return value

        async def read_inside_lock(household_id):
            self.read_under_lock.append(household_cycle.household_lock(household_id).locked())
            return self.stored[household_id]

        self.current_payday = AsyncMock(side_effect=read_inside_lock)
        self.enterContext(patch("app.core.database.AsyncSessionLocal", lambda: FakeSession(self.db, on_close)))
        self.enterContext(patch.object(household_cycle, "household_payday", first_read))
        self.enterContext(patch.object(household_cycle, "heal", self.heal))
        self.enterContext(patch.object(household_cycle, "current_payday", self.current_payday))
        self.enterContext(patch.object(scheduler, "create_monthly_snapshots", self.create))
        self.enterContext(patch.object(scheduler, "date", fixed_date(today)))

    async def yield_to_job(self):
        """Beri task job giliran berjalan sampai ia selesai atau tertahan sesuatu (kunci, event)."""
        for _ in range(10):
            await asyncio.sleep(0)


class PaydaySnapshotJobTests(JobTestCase):
    async def test_job_heals_and_snapshots_per_household(self):
        h1, h2 = make_household(), make_household()
        self.setup_job([h1, h2], payday=[1, 25])

        await scheduler.payday_snapshot_job()

        self.assertEqual(self.household_payday.await_args_list, [call(self.db, h1), call(self.db, h2)])
        self.assertEqual(self.heal.await_count, 2)
        self.assertEqual(self.heal.await_args_list, [call(self.db, h1), call(self.db, h2)])
        # Enam panggilan, masing-masing untuk TEPAT SATU household dan tanpa `force`: h1 hanya dengan jendela payday 1,
        # h2 hanya dengan jendela payday 25, tiap jendela oldest-first.
        self.assertEqual(self.create.await_count, 6)
        self.assertEqual(
            self.create.await_args_list,
            [call(start, end, household_ids=[h1.id]) for start, end in PERIODS_PAYDAY_1]
            + [call(start, end, household_ids=[h2.id]) for start, end in PERIODS_PAYDAY_25],
        )

    async def test_job_only_households_with_members(self):
        # Household tanpa anggota (sisa yang ditinggalkan user yang pindah household) tidak diproses.
        self.setup_job([], payday=[])

        await scheduler.payday_snapshot_job()

        statements = [norm(statement) for statement in executed_sql(self.db)]
        self.assertEqual(len(statements), 1)  # satu kueri household; tanggal dan anggota datang dari service
        self.assertIn("household_members", statements[0])
        self.assertIn("FROM households", statements[0])
        self.assertIn(
            "households.id IN (SELECT household_members.household_id FROM household_members)", statements[0]
        )

    async def test_job_without_households_does_nothing(self):
        self.setup_job([], payday=[])

        await scheduler.payday_snapshot_job()

        self.household_payday.assert_not_awaited()
        self.heal.assert_not_awaited()
        self.create.assert_not_awaited()

    async def test_job_commits_and_closes_the_session_before_snapshotting(self):
        # `household_payday` mengisi tanggal rumah yang NULL (flush) dan `heal` memperbaiki cermin di sesi job,
        # sedangkan `create_monthly_snapshots` bekerja lewat sesinya sendiri: simpan dulu (satu commit), tutup sesi,
        # baru snapshot (kontrak yang sama dengan `recompute_history` dan `POST /snapshots/run`). `household_payday`
        # harus lebih dulu dari `heal`, yang melewati household yang tanggalnya masih NULL.
        h1, h2 = make_household(), make_household()
        log = []
        paydays = iter([1, 25])

        async def payday(_db, household):
            log.append(("payday", household.id))
            return next(paydays)

        async def heal(_db, household):
            log.append(("heal", household.id))
            return []

        async def create(start, end, **kwargs):
            log.append(("create", kwargs["household_ids"][0], start))
            return dict(NOTHING_CREATED)

        self.setup_job([h1, h2], payday=payday, heal=heal, create=create, on_close=lambda: log.append("close"))
        self.db.commit.side_effect = lambda: log.append("commit")

        await scheduler.payday_snapshot_job()

        self.assertEqual(log, [
            ("payday", h1.id), ("heal", h1.id), ("payday", h2.id), ("heal", h2.id),
            "commit", "close",
            *[("create", h1.id, start) for start, _ in PERIODS_PAYDAY_1],
            *[("create", h2.id, start) for start, _ in PERIODS_PAYDAY_25],
        ])

    async def test_job_logs_household_and_payday_for_created_snapshots(self):
        h1, h2 = make_household(), make_household()
        built = {"processed": 3, "snapshots_created": 2, "errors": ["Makan: boom"]}
        # Hanya periode pertama h2 yang menghasilkan snapshot baru; sisanya sudah ada.
        created = [NOTHING_CREATED] * 3 + [built, NOTHING_CREATED, NOTHING_CREATED]
        self.setup_job([h1, h2], payday=[1, 25], create=created)

        with self.assertLogs("jatahku.scheduler", "INFO") as logs:
            await scheduler.payday_snapshot_job()

        self.assertEqual(len(logs.records), 1)  # periode tanpa snapshot baru tidak dicatat, seperti sebelumnya
        message = logs.records[0].getMessage()
        for part in (f"household={h2.id} payday=25", "2026-07-25 → 2026-08-24", "2 snapshots created", "1 errors"):
            self.assertIn(part, message)


class HouseholdLockTests(unittest.TestCase):
    def test_household_lock_is_one_lock_per_household(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        self.assertIsInstance(household_cycle.household_lock(a), asyncio.Lock)
        self.assertIs(household_cycle.household_lock(a), household_cycle.household_lock(a))
        self.assertIsNot(household_cycle.household_lock(a), household_cycle.household_lock(b))


class JobLockTests(JobTestCase):
    """R10: job harian dan `recompute_history` menulis kunci snapshot `(envelope_id, year, month)` yang sama (recompute
    menghapus lalu menyisipkan ulang), jadi keduanya tidak boleh berjalan bersamaan pada household yang sama."""

    async def test_job_waits_for_a_held_household_lock(self):
        h = make_household()
        self.setup_job([h], payday=[1])
        lock = household_cycle.household_lock(h.id)

        async with lock:  # misalnya recompute household ini sedang berjalan
            job = asyncio.create_task(scheduler.payday_snapshot_job())
            await self.yield_to_job()
            self.assertFalse(job.done())
            self.create.assert_not_awaited()

        await asyncio.wait_for(job, timeout=1)
        self.assertEqual(self.create.await_count, 3)
        self.assertFalse(lock.locked())  # job melepas kunci setelah selesai

    async def test_job_lock_is_per_household(self):
        h1, h2 = make_household(), make_household()
        self.setup_job([h1, h2], payday=[1, 25])

        async with household_cycle.household_lock(h2.id):
            job = asyncio.create_task(scheduler.payday_snapshot_job())
            await self.yield_to_job()
            self.assertFalse(job.done())  # h2 menunggu kuncinya...
            self.assertEqual(  # ...sedangkan h1 tidak terhalang kunci household lain
                self.create.await_args_list, [call(s, e, household_ids=[h1.id]) for s, e in PERIODS_PAYDAY_1]
            )

        await asyncio.wait_for(job, timeout=1)
        self.assertEqual(
            self.create.await_args_list[3:], [call(s, e, household_ids=[h2.id]) for s, e in PERIODS_PAYDAY_25]
        )

    async def test_job_holds_the_lock_for_every_period_and_releases_it_after(self):
        h1, h2 = make_household(), make_household()
        held = []

        async def create(start, end, **kwargs):
            own = kwargs["household_ids"][0]
            other = h2.id if own == h1.id else h1.id
            held.append((household_cycle.household_lock(own).locked(), household_cycle.household_lock(other).locked()))
            return dict(NOTHING_CREATED)

        self.setup_job([h1, h2], payday=[1, 25], create=create)

        await scheduler.payday_snapshot_job()

        self.assertEqual(held, [(True, False)] * 6)  # kunci household sendiri saja, di setiap periode
        for h in (h1, h2):
            self.assertFalse(household_cycle.household_lock(h.id).locked())

    async def test_job_and_recompute_history_exclude_each_other(self):
        h = make_household()
        log = []
        release = asyncio.Event()

        async def create(start, end, **kwargs):
            log.append("job: mulai periode")
            await release.wait()
            log.append("job: selesai periode")
            return dict(NOTHING_CREATED)

        async def recompute_household(household_id, payday, periods):
            log.append("recompute")
            return []

        self.setup_job([h], payday=[1], create=create)
        self.enterContext(patch.object(household_cycle.rollover, "recompute_household", recompute_household))

        job = asyncio.create_task(scheduler.payday_snapshot_job())
        await self.yield_to_job()  # job memegang kunci, tertahan di periode pertama
        recompute = asyncio.create_task(household_cycle.recompute_history(h.id, 12))
        await self.yield_to_job()
        self.assertEqual(log, ["job: mulai periode"])  # recompute menunggu job

        release.set()
        await asyncio.wait_for(asyncio.gather(job, recompute), timeout=1)
        # Satu kali pegang untuk seluruh loop household: recompute baru masuk setelah ketiga periode job selesai,
        # bukan di sela-selanya.
        self.assertEqual(log, ["job: mulai periode", "job: selesai periode"] * 3 + ["recompute"])


class JobPaydayReadTests(JobTestCase):
    """R16: tanggal gajian untuk jendela snapshot dibaca ulang DI DALAM kunci household (`current_payday`), bukan
    dipakai dari bacaan tahap pertama yang bisa basi. Pemilik bisa mengubah tanggal kapan saja; `set_household_payday`
    commit dulu, lalu `recompute_history` (di bawah kunci yang sama) menulis ulang riwayat dan membuang kunci periode
    berjalan menurut tanggal baru. Jendela basi yang ditulis sesudahnya membuat snapshot untuk periode yang masih
    berjalan, dan tidak ada yang menimpanya lagi (job tanpa `force` melewati kunci yang sudah ada), jadi rollover salah
    terbawa terus."""

    async def test_job_builds_windows_from_the_payday_read_inside_the_lock(self):
        h = make_household()
        built = {"processed": 3, "snapshots_created": 3, "errors": []}
        # Tahap pertama membaca 1, tetapi saat job memegang kunci tanggal yang tersimpan sudah 25.
        self.setup_job([h], payday=[1], fresh={h.id: 25}, create=[built, NOTHING_CREATED, NOTHING_CREATED])

        with self.assertLogs("jatahku.scheduler", "INFO") as logs:
            await scheduler.payday_snapshot_job()

        self.assertEqual(self.household_payday.await_args_list, [call(self.db, h)])  # tahap pertama tetap jalan
        self.assertEqual(self.current_payday.await_args_list, [call(h.id)])
        self.assertEqual(
            self.create.await_args_list, [call(s, e, household_ids=[h.id]) for s, e in PERIODS_PAYDAY_25]
        )
        self.assertEqual(len(logs.records), 1)
        self.assertIn(f"household={h.id} payday=25", logs.records[0].getMessage())  # tanggal yang dipakai, bukan 1

    async def test_job_reads_the_payday_after_taking_the_lock(self):
        # Dibaca sebelum kunci (atau semua di muka) berarti tanggalnya bisa basi lagi selagi menunggu giliran.
        h1, h2 = make_household(), make_household()
        self.setup_job([h1, h2], payday=[1, 25])

        await scheduler.payday_snapshot_job()

        self.assertEqual(self.current_payday.await_args_list, [call(h1.id), call(h2.id)])
        self.assertEqual(self.read_under_lock, [True, True])

    async def test_job_skips_a_household_that_vanished_before_its_lock(self):
        # Household dihapus (merge / penghapusan akun) setelah tahap pertama: dilewati dengan peringatan, yang lain
        # tetap diproses, dan kuncinya dilepas.
        h1, h2 = make_household(), make_household()
        self.setup_job([h1, h2], payday=[1, 25], fresh={h1.id: None})

        with self.assertLogs("jatahku.scheduler", "WARNING") as logs:
            await scheduler.payday_snapshot_job()

        self.assertEqual(
            self.create.await_args_list, [call(s, e, household_ids=[h2.id]) for s, e in PERIODS_PAYDAY_25]
        )
        self.assertEqual(len(logs.records), 1)
        self.assertIn(str(h1.id), logs.records[0].getMessage())
        self.assertFalse(household_cycle.household_lock(h1.id).locked())

    async def run_with_payday_change(self, *, rebuild_done_before_job_arrives):
        """Balapan dari review, 10 Nov 2026. Household B terbaca payday 1 di tahap pertama; selagi job sibuk dengan
        household A (dua household, A lebih dulu), pemilik B mengubahnya jadi 25: tanggal di-commit, lalu
        `recompute_history` (asli) memegang kunci B dan membangun ulang (`rollover.recompute_household` palsu yang
        tertahan sampai dilepas). `rebuild_done_before_job_arrives`: rebuild sudah selesai sebelum job sampai ke B, atau
        masih memegang kunci B saat job datang dan harus ditunggu. Mengembalikan household (a, b)."""
        a, b = make_household(), make_household()
        release_a, release_rebuild = asyncio.Event(), asyncio.Event()
        rebuilds = []

        async def create(start, end, **kwargs):
            if kwargs["household_ids"] == [a.id]:
                await release_a.wait()  # A "lambat": B baru diproses sesudahnya
            return dict(NOTHING_CREATED)

        async def rebuild(household_id, payday, periods):
            rebuilds.append((household_id, payday))
            await release_rebuild.wait()
            return []

        self.setup_job([a, b], payday=[1, 1], create=create, today=RACE_DAY)
        self.enterContext(patch.object(household_cycle.rollover, "recompute_household", rebuild))

        job = asyncio.create_task(scheduler.payday_snapshot_job())
        await self.yield_to_job()  # tahap pertama selesai (B terbaca 1); job di dalam kunci A, tertahan di pekerjaannya
        self.stored[b.id] = 25
        recompute = asyncio.create_task(household_cycle.recompute_history(b.id, 12))
        await self.yield_to_job()
        self.assertEqual(rebuilds, [(b.id, 25)])  # recompute memegang kunci B dengan tanggal baru

        if rebuild_done_before_job_arrives:
            release_rebuild.set()
            await asyncio.wait_for(recompute, timeout=1)
        release_a.set()  # job lanjut ke B
        await self.yield_to_job()
        if not rebuild_done_before_job_arrives:
            self.assertFalse(job.done())  # kunci B masih dipegang rebuild: job menunggu
            release_rebuild.set()
        await asyncio.wait_for(asyncio.gather(job, recompute), timeout=1)
        return a, b

    def windows_for(self, household):
        calls = [c for c in self.create.await_args_list if c.kwargs["household_ids"] == [household.id]]
        return [(c.args[0], c.args[1]) for c in calls]

    async def test_payday_change_while_job_waits_for_the_rebuild_never_recreates_the_open_period_key(self):
        a, b = await self.run_with_payday_change(rebuild_done_before_job_arrives=False)

        self.assertEqual(self.windows_for(b), PERIODS_PAYDAY_25)
        # Oktober (1-31 Okt) adalah kunci 2026-10 = periode BERJALAN B menurut payday 25 (25 Okt-24 Nov), yang baru saja
        # dibuang rebuild: tidak boleh ditulis ulang dengan angka 1-31 Okt.
        self.assertNotIn((date(2026, 10, 1), date(2026, 10, 31)), self.windows_for(b))
        self.assertEqual(self.windows_for(a), PERIODS_PAYDAY_1_ON_RACE_DAY)  # A tidak berubah

    async def test_payday_change_done_before_the_job_arrives_never_recreates_the_open_period_key(self):
        a, b = await self.run_with_payday_change(rebuild_done_before_job_arrives=True)

        self.assertEqual(self.windows_for(b), PERIODS_PAYDAY_25)
        self.assertNotIn((date(2026, 10, 1), date(2026, 10, 31)), self.windows_for(b))
        self.assertEqual(self.windows_for(a), PERIODS_PAYDAY_1_ON_RACE_DAY)


if __name__ == "__main__":
    unittest.main()
