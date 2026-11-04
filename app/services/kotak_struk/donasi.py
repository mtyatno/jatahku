"""Donasi contoh Kotak Struk (belajar lintas user tahap 2; spec 2026-11-01 §10 Tahap 2 butir 1, §12.4).

User yang SETUJU (opt-in di Settings) menyumbang baris teks bukti TERSAMAR dari bukti bayar yang ia koreksi; pemilik
meninjaunya di Admin dan menyalin yang disetujui ke korpus pembaca. Semuanya di balik saklar `features.kotak_donasi`
(bawaan mati, pre-flight A16 K1/G1): kebijakan privasi yang tayang harus memuat paragraf donasi dulu.

Bagian M1a: saklar, persetujuan, dan lupa. Bagian M1b: `sample_lines` (baris tersamar yang ditangkap worker). Bagian
M1c: `correction_trigger` dan `donate` (koreksi memindahkan baris ke antrean tinjauan `proof_samples`).
- `donation_available`: saklar menyala (web).
- `consented` / `set_consent`: satu baris `proof_sample_consents` per user; menyalakan idempoten (waktu pertama tetap),
  mematikan = menghapus baris itu dan `forget_user(keep_approved=True)` (sampel yang sudah disetujui pemilik tetap).
- `sample_lines` (M1b, pre-flight A16 §2, K5, G6): dari teks OCR dan hasil baca SEBELUM disamarkan (titik yang sama
  dengan kerangka tata letak worker), hanya dipanggil worker untuk user yang setuju saat saklar menyala.
- `correction_trigger` / `donate` (M1c, pre-flight A16 §2 "Trigger points", K3, G7): titik koreksi yang sudah ada
  (`record.mark_recorded`, `record.skip_item`, `record.choose_app`, bot "Nominal salah") memanggil `donate`; koreksi
  memindahkan `sample_lines` ke `proof_samples` (status `menunggu`), selain itu (bacaan benar, `batal`/`duplikat`,
  persetujuan ditarik, saklar mati) baris itu dikosongkan. Pembersihan umur sampel: `maintenance.purge_samples`.
- `forget_user` (G4): persetujuan user, `proof_samples`-nya, dan `receipt_scans.sample_lines` miliknya. Hapus akun
  (`account_deletion.delete_account`) dan gabung akun (`merge.merge_users`, source; persetujuan tidak diwariskan ke
  target) menghapus SEMUA sampel; menarik persetujuan menyisakan sampel yang sudah `disetujui` (keputusan pemilik).
- Urutan kunci (review M1c temuan 1, 5): selalu baris persetujuan SEBELUM `receipt_scans`. `forget_user` menghapus
  persetujuan lebih dulu; pendonor yang mengunci baris item (lewati, jawaban aplikasi) mengambil kunci persetujuan
  (`lock_consent`) sebelum itu.

Tidak ada fungsi di sini yang meng-commit; pemanggil (route, hapus akun, gabung akun) meng-commit. Modul ini tidak
menanyakan keanggotaan household (`test_ruang_pagar`).
"""
from __future__ import annotations

import re
import uuid
import logging
from datetime import date, datetime, timezone

from sqlalchemy import delete, exists, null, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.exc import UnmappedInstanceError

from app.models.models import ProofSample, ProofSampleConsent, ReceiptScan, User
from app.services.app_config import feature_enabled
from app.services.kotak_struk import belajar, kerangka, samaran
from app.services.kotak_struk.config import PROOF_TYPES, SAMPLE_LINE_MAX, SAMPLE_MAX_LINES, SAMPLE_TYPES
from app.services.kotak_struk.document import DokumenBayar
from app.services.kotak_struk.extract import KIND_IMAGE, TextDoc
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.base import Secrets
from app.services.kotak_struk.readers.labels import WIB
from app.services.kotak_struk.registry import looks_like_proof

log = logging.getLogger(__name__)

FEATURE = "kotak_donasi"


async def donation_available(db: AsyncSession) -> bool:
    """Saklar donasi contoh (`features.kotak_donasi`, web). Mati: tidak ada tombol di Settings dan tidak ada baris yang
    ditangkap; menarik persetujuan tetap bisa."""
    return await feature_enabled(db, FEATURE, "web")


async def consented(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """User ini sudah menyalakan donasi contoh (ada baris persetujuan)."""
    return bool((await db.execute(
        select(exists().where(ProofSampleConsent.user_id == user_id)))).scalar())


def _locked_consent(user_id: uuid.UUID):
    """SELECT baris persetujuan `... FOR SHARE` (review M1c temuan 1): menarik persetujuan (`forget_user` menghapus
    baris ini lebih dulu) menunggu transaksi pembaca selesai, lalu menghapus sampel/baris yang baru di-commit-nya;
    pembaca yang datang sesudah penghapusan menunggu dan tidak melihat barisnya lagi. SQLite mengabaikan kuncinya."""
    return select(ProofSampleConsent.user_id).where(ProofSampleConsent.user_id == user_id).with_for_update(read=True)


async def lock_consent(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Ambil kunci FOR SHARE baris persetujuan user (bila ada) sampai transaksi pemanggil selesai, SEBELUM pemanggil
    mengunci baris `receipt_scans` (review M1c temuan 5: urutan kunci sama dengan `forget_user`, persetujuan lalu
    item, supaya lewati/jawaban aplikasi dan penarikan bersamaan tidak saling menunggu). SAVEPOINT; tidak pernah
    melempar (galat -> log jenis galat saja); tidak meng-commit."""
    try:
        async with db.begin_nested():
            await db.execute(_locked_consent(user_id))
    except Exception as exc:
        log.warning("kunci persetujuan donasi Kotak Struk tidak diambil (%s)", type(exc).__name__)


async def still_consented(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Saklar menyala DAN persetujuan user masih ada, dibaca dengan kunci FOR SHARE sampai transaksi pemanggil selesai.
    Dipakai tepat sebelum menulis baris tersamar (worker `_store`) atau sampel (`donate`)."""
    if not await donation_available(db):
        return False
    return (await db.execute(_locked_consent(user_id))).first() is not None


async def consented_at(db: AsyncSession, user_id: uuid.UUID) -> datetime | None:
    """Waktu user menyalakan donasi contoh, atau None bila belum/sudah ditarik."""
    return (await db.execute(
        select(ProofSampleConsent.consented_at).where(ProofSampleConsent.user_id == user_id))).scalar_one_or_none()


async def set_consent(db: AsyncSession, user_id: uuid.UUID, on: bool, *, now: datetime) -> datetime | None:
    """Nyalakan (`on`) atau tarik persetujuan donasi contoh. Menyalakan idempoten: baris yang sudah ada tidak diubah
    (waktu persetujuan pertama tetap), dua permintaan bersamaan tidak menggagalkan satu sama lain (SAVEPOINT);
    mengembalikan waktu persetujuan. Menarik: `forget_user(keep_approved=True)` (baris persetujuan, sampel
    `menunggu`/`ditolak`, dan baris tersamar user ini dihapus; sampel yang sudah `disetujui` pemilik tetap sampai
    SAMPLE_TTL); mengembalikan None. Tidak memeriksa saklar (route yang menolak menyalakan saat saklar mati) dan
    tidak meng-commit."""
    if not on:
        await forget_user(db, user_id, keep_approved=True)
        return None
    current = await consented_at(db, user_id)
    if current is not None:
        return current
    try:
        async with db.begin_nested():
            db.add(ProofSampleConsent(user_id=user_id, consented_at=now))
            await db.flush()
    except IntegrityError:   # permintaan lain baru saja menyalakannya: pakai baris itu
        pass
    return await consented_at(db, user_id)


async def forget_user(db: AsyncSession, user_id: uuid.UUID, *, keep_approved: bool = False) -> None:
    """Lupakan donasi user ini (G4): hapus baris persetujuannya, `proof_samples`-nya (menunggu, disetujui, ditolak;
    `keep_approved`: yang `disetujui` tetap, keputusan pemilik saat menarik persetujuan), dan kosongkan
    `receipt_scans.sample_lines` miliknya (SQL NULL). Hapus akun dan gabung akun memakai bawaan (semua). Sampel milik user lain yang pernah
    ia putuskan sebagai admin tidak disentuh (pemanggil hapus akun mengosongkan `decided_by`). Tidak meng-commit.

    Urutan (review M1c temuan 1): baris persetujuan DIHAPUS LEBIH DULU. Pendonor yang sedang memegang kunci FOR SHARE
    (`still_consented`) membuat DELETE ini menunggu sampai ia commit; pernyataan berikutnya (READ COMMITTED: snapshot
    baru) lalu menghapus sampel dan baris tersamar yang baru di-commit itu."""
    await db.execute(delete(ProofSampleConsent).where(ProofSampleConsent.user_id == user_id))
    samples = delete(ProofSample).where(ProofSample.user_id == user_id)
    if keep_approved:
        samples = samples.where(ProofSample.status != "disetujui")
    await db.execute(samples)
    await db.execute(
        update(ReceiptScan)
        .where(ReceiptScan.user_id == user_id, ReceiptScan.sample_lines.is_not(None))
        .values(sample_lines=null())
        .execution_options(synchronize_session=False)
    )


# ── Baris tersamar (M1b) ────────────────────────────────────────────────────

_LONG_DIGITS = re.compile(r"\d{%d,}" % samaran.MIN_RUN_DIGITS)
_NMID_LINE = re.compile(r"nmid", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
GROUPED_MIN_DIGITS = 10
_GROUPED_NUMBER = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?(?![\d])")
_AFTER_CURRENCY = re.compile(r"(?:rp|idr)\s*[.:]?\s*$", re.IGNORECASE)


# Kata kosakata label/status/arah uang (bukan nama). Kata penyedia/logo/penanda aplikasi di `kerangka.TITLE_WORDS`
# ("mega", "neo", "jago", "mandiri", "permata") sering juga nama orang, jadi tidak termasuk (review M1b temuan 1). Sisa
# risiko: "dana" kata label ("Sumber Dana") sekaligus nama depan; nama itu di tebakan pembaca struk tidak disamarkan
# otomatis, pemilik meninjaunya di Admin.
_VOCAB_WORDS: frozenset[str] = kerangka.LABEL_WORDS | frozenset(kerangka._TITLE_EXTRA.split())


def _party_name(doc: DokumenBayar) -> str | None:
    """Nama pihak lawan dokumen. Bukti yang tidak dibaca pembaca QRIS/transfer (struk belanja/tidak dikenali): "nama"-nya
    tebakan pembaca struk, sering judul status atau logo aplikasi ("Transfer Berhasil", "Bca Mobile"; worker membuangnya
    dari Dokumen Bayar). Tebakan yang SEMUA katanya kosakata judul (`kerangka.TITLE_WORDS`) bukan nama (None). Selain itu
    hanya kata kosakata label/status (`_VOCAB_WORDS`) yang tidak disamarkan; kata lain, juga kata penyedia/logo,
    disamarkan ("Penerima Budi" -> "Budi"; "Mega Lestari" -> kedua katanya)."""
    name = doc.counterparty.name
    if not name or doc.doc_type in PROOF_TYPES:
        return name
    words = [(w, kerangka.words(w)) for w in name.split()]
    words = [(w, norm[0]) for w, norm in words if norm]
    if all(norm in kerangka.TITLE_WORDS for _w, norm in words):
        return None
    return " ".join(w for w, norm in words if norm not in _VOCAB_WORDS) or None


def _known_names(clean: list[str], doc: DokumenBayar, user_name: str | None) -> dict[str, str | None]:
    """Nama yang dikenal per peran samaran: pihak lawan dokumen (`_party_name`), pengirim tercetak, merchant yang dibaca
    pembaca bukti dari baris berlabel, dan user (sumber yang sama dengan `kerangka._forbidden_words`)."""
    profile = kerangka._profile_of(doc, clean)
    try:   # pembaca nama hanya tambahan pengaman
        merchant = pc.read_name(pc.body_lines(clean), profile, "merchant")
    except Exception:
        merchant = None
    return {"pihak": _party_name(doc), "pengirim": pc.read_sender_name(clean, profile), "merchant": merchant,
            "user": user_name}


def _grouped_account(line: str) -> bool:
    """Ada nomor berkelompok ribuan >= GROUPED_MIN_DIGITS digit yang tidak langsung sesudah Rp/IDR ("Rek 1.234.567.890":
    `mask_line` membiarkannya karena berbentuk nominal). "Rp 1.234.567" tetap."""
    for m in _GROUPED_NUMBER.finditer(line):
        if sum(c.isdigit() for c in m.group()) >= GROUPED_MIN_DIGITS and not _AFTER_CURRENCY.search(line[:m.start()]):
            return True
    return False


def _holds_secret(line: str, secrets: Secrets) -> bool:
    """Baris masih memuat nilai rahasia (nomor referensi, rekening, NMID di luar baris berlabel NMID), deret >= 6 digit,
    alamat email, atau nomor berkelompok ribuan >= 10 digit di luar Rp/IDR (review M1b temuan 2, 3).

    Dua aturan terakhir (email, nomor berkelompok) juga harus diterapkan pemeriksaan persetujuan Admin (M1d) pada baris
    editan, bersama `\\d{6,}`."""
    if _LONG_DIGITS.search(line) or _EMAIL.search(line) or _grouped_account(line):
        return True
    digits = re.sub(r"\D", "", line)
    values = [*secrets.ref_values, secrets.account_number]
    if not _NMID_LINE.search(line):
        values.append(secrets.nmid)
    for value in values:
        value = (value or "").strip()
        if not value:
            continue
        if len(value) >= 4 and value.lower() in line.lower():
            return True
        value_digits = re.sub(r"\D", "", value)
        if len(value_digits) >= pc.LONG_DIGITS and value_digits in digits:
            return True
    return False


def sample_lines(lines: list[str], doc: DokumenBayar, secrets: Secrets, *, user_name: str | None) -> list[str] | None:
    """Baris tersamar satu bukti untuk donasi contoh, atau None.

    Hanya bukti bayar (G6): `doc.doc_type` di SAMPLE_TYPES, atau teks yang tampak bukti (`looks_like_proof`; bukti yang
    dibaca pembaca struk); struk belanja biasa tidak pernah. `lines` = baris OCR mentah, `doc`/`secrets` = hasil pembaca
    SEBELUM disamarkan worker. Langkah: `clean_lines` -> `samaran.mask_line` -> `samaran.pseudonymise` (nama pihak lawan,
    pengirim, merchant terbaca, user) -> baris yang masih memuat nilai `secrets` atau deret >= 6 digit dibuang -> paling
    banyak SAMPLE_MAX_LINES baris, masing-masing SAMPLE_LINE_MAX karakter. None juga bila tidak ada baris tersisa."""
    if doc.doc_type not in SAMPLE_TYPES and not looks_like_proof(TextDoc(lines=list(lines), kind=KIND_IMAGE)):
        return None
    clean = pc.clean_lines(lines)
    masked = [samaran.mask_line(line) for line in clean]
    named, _user = samaran.pseudonymise(masked, _known_names(clean, doc, user_name))
    kept = [line[:SAMPLE_LINE_MAX] for line in named if not _holds_secret(line, secrets)]
    return kept[:SAMPLE_MAX_LINES] or None


# ── Koreksi -> antrean tinjauan (M1c) ───────────────────────────────────────

TRIGGER_NOMINAL = "nominal"
TRIGGER_TANGGAL = "tanggal"
TRIGGER_TIDAK_DIKENALI = "tidak_dikenali"
TRIGGER_ARAH = "arah"
TRIGGER_APLIKASI = "aplikasi"
TRIGGER_NOMINAL_BOT = "nominal_bot"
TRIGGERS = (TRIGGER_NOMINAL, TRIGGER_TANGGAL, TRIGGER_TIDAK_DIKENALI, TRIGGER_ARAH, TRIGGER_APLIKASI,
            TRIGGER_NOMINAL_BOT)
SKIP_NOT_EXPENSE = "bukan_pengeluaran"   # sama dengan record.SKIP_NOT_EXPENSE (record mengimpor modul ini)
ST_SAMPLE_WAITING = "menunggu"
RULE_KEY_MAX = 60                        # proof_samples.rule_key String(60)


def truth_of(*, total: int | None = None, day: date | None = None, flow: str | None = None,
             app: str | None = None) -> dict:
    """Petunjuk kebenaran dari koreksi user untuk pemilik (G7): `{total, date, flow, app}`; tanggal ISO."""
    return {"total": total, "date": day.isoformat() if day is not None else None, "flow": flow, "app": app}


def correction_trigger(item, final: belajar.Final | None, *, skip_reason: str | None = None,
                       alasan: str | None = None, app: str | None = None,
                       typed_amount: int | None = None) -> str | None:
    """Jenis koreksi yang membuat bukti `item` layak menjadi sampel donasi, atau None (pre-flight A16 K3 opsi B). Murni.

    - `aplikasi`: jawaban "Aplikasi apa ini?" (`app`); `nominal_bot`: nominal ketikan sesudah "Nominal salah"
      (`typed_amount`) yang beda dari total terbaca (sama -> None).
    - Lewati (`skip_reason`): `batal`/`duplikat` -> None. `bukan_pengeluaran`: `arah` bila `alasan` beda dari
      `document.flow`; selain itu `tidak_dikenali` untuk item `tidak_dikenali`; selain itu `arah` bila tanpa alasan
      dan arah terbaca `keluar`; selain itu None.
    - Tercatat (`final` dari transaksi yang tercatat): `nominal` bila nominal tercatat beda dari total terbaca (juga
      bila total tidak terbaca); `tanggal` bila tanggal tercatat bukan tanggal bukti (WIB) dan bukan hari ini;
      `tidak_dikenali` bila item `tidak_dikenali`; selain itu None (bacaan benar)."""
    if app is not None:
        return TRIGGER_APLIKASI
    document = getattr(item, "document", None)
    document = document if isinstance(document, dict) else {}
    amounts = document.get("amounts") if isinstance(document.get("amounts"), dict) else {}
    if typed_amount is not None:   # nominal ketikan sama dengan total terbaca: bukan koreksi (review M1c catatan 2)
        return None if typed_amount == amounts.get("total") else TRIGGER_NOMINAL_BOT
    doc_type = getattr(item, "doc_type", None)
    if skip_reason is not None:
        if skip_reason != SKIP_NOT_EXPENSE:
            return None
        flow = document.get("flow")
        if alasan is not None and alasan != flow:
            return TRIGGER_ARAH
        if doc_type == "tidak_dikenali":
            return TRIGGER_TIDAK_DIKENALI
        if alasan is None and flow == "keluar":
            return TRIGGER_ARAH
        return None
    if final is None:
        return None
    total = amounts.get("total")
    if total is None or final.amount != total:
        return TRIGGER_NOMINAL
    if final.txn_date is not None and final.txn_date != final.today and final.txn_date != belajar._doc_date(document):
        return TRIGGER_TANGGAL
    if doc_type == "tidak_dikenali":
        return TRIGGER_TIDAK_DIKENALI
    return None


def _forget_local(item) -> None:
    """`sample_lines` objek pemanggil = None tanpa membuatnya kotor (baris sudah dikosongkan lewat UPDATE)."""
    try:
        set_committed_value(item, "sample_lines", None)
    except (UnmappedInstanceError, AttributeError):
        setattr(item, "sample_lines", None)


def _sample_day(processed_at: datetime | None, now: datetime) -> date:
    """`today` sampel: hari baca bukti menurut WIB (tanpa zona = UTC, seperti worker); belum dibaca -> hari `now`."""
    moment = processed_at or now
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(WIB).date()


async def donate(db: AsyncSession, item, trigger: str | None, *, truth: dict, now: datetime) -> bool:
    """Pindahkan baris tersamar item Kotak Struk `item` (`sample_lines`) ke antrean tinjauan; True bila sampel baru
    disimpan.

    Tanpa `sample_lines` -> False tanpa kueri. Selain itu, dalam SAVEPOINT sendiri: bila `trigger` ada, saklar
    `kotak_donasi` menyala, DAN user pemilik item MASIH setuju (dicek lagi di sini dengan kunci FOR SHARE,
    `still_consented`: persetujuan bisa ditarik selagi bukti dibaca atau bersamaan, review M1b temuan 5, M1c temuan 1),
    sisip `ProofSample(status="menunggu", lines, rule_key dari kerangka, doc_type,
    trigger, user_name = nama samaran user, truth, today = hari baca WIB)` dengan `on_conflict_do_nothing` pada
    `uq_proof_sample_item` (satu sampel per item; kirim ulang tidak menggandakan). Dalam SEMUA kasus itu
    `receipt_scans.sample_lines` item dikosongkan (SQL NULL). Tidak meng-commit (pemanggil meng-commit bersama
    pencatatan/lewati). Tidak pernah melempar: galat -> log tanpa isi bukti + False (savepoint dibatalkan; baris
    dikosongkan di savepoint baru bila bisa, selain itu pemeliharaan menghapusnya). Tidak membuat transaksi dan tidak
    mengubah status item."""
    item_id = getattr(item, "id", None)
    try:
        lines = getattr(item, "sample_lines", None)
        if not lines:
            return False
        stored = False
        async with db.begin_nested():
            user_id = item.user_id
            if trigger is not None and await still_consented(db, user_id):
                name = (await db.execute(select(User.name).where(User.id == user_id))).scalar_one_or_none()
                layout = getattr(item, "layout", None)
                key = layout.get("key") if isinstance(layout, dict) else None
                res = await db.execute(
                    pg_insert(ProofSample)
                    .values(id=uuid.uuid4(), user_id=user_id, item_id=item_id,
                            rule_key=key[:RULE_KEY_MAX] if isinstance(key, str) else None,
                            doc_type=item.doc_type or "", trigger=trigger, lines=list(lines),
                            user_name=samaran.pseudonymise([], {"user": name})[1] if name else None,
                            truth=truth, today=_sample_day(getattr(item, "processed_at", None), now),
                            status=ST_SAMPLE_WAITING, created_at=now)
                    .on_conflict_do_nothing(index_elements=[ProofSample.item_id])
                )
                stored = (res.rowcount or 0) == 1
            await _clear_lines(db, item_id)
        _forget_local(item)
        return stored
    except Exception as exc:
        log.warning("sampel donasi Kotak Struk untuk item %s tidak disimpan (%s)", item_id, type(exc).__name__)
        try:   # baris tetap dikosongkan bila bisa (savepoint baru); bila tidak, pemeliharaan menghapusnya
            async with db.begin_nested():
                await _clear_lines(db, item_id)
            _forget_local(item)
        except Exception:
            pass
        return False


async def _clear_lines(db: AsyncSession, item_id) -> None:
    await db.execute(
        update(ReceiptScan).where(ReceiptScan.id == item_id).values(sample_lines=null())
        .execution_options(synchronize_session=False)
    )
