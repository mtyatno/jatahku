"""Donasi contoh Kotak Struk (belajar lintas user tahap 2; spec 2026-11-01 §10 Tahap 2 butir 1, §12.4).

User yang SETUJU (opt-in di Settings) menyumbang baris teks bukti TERSAMAR dari bukti bayar yang ia koreksi; pemilik
meninjaunya di Admin dan menyalin yang disetujui ke korpus pembaca. Semuanya di balik saklar `features.kotak_donasi`
(bawaan mati, pre-flight A16 K1/G1): kebijakan privasi yang tayang harus memuat paragraf donasi dulu.

Bagian M1a: saklar, persetujuan, dan lupa. Bagian M1b: `sample_lines` (baris tersamar yang ditangkap worker). Bagian
M1c: `correction_trigger` dan `donate` (koreksi memindahkan baris ke antrean tinjauan `proof_samples`). Bagian M1d:
tinjauan Admin dan entri korpus.
- `donation_available`: saklar menyala (web).
- `consented` / `set_consent`: satu baris `proof_sample_consents` per user; menyalakan idempoten (waktu pertama tetap),
  mematikan = menghapus baris itu dan `forget_user(keep_approved=True)` (sampel yang sudah disetujui pemilik tetap).
- `sample_lines` (M1b, pre-flight A16 §2, K5, G6): dari teks OCR dan hasil baca SEBELUM disamarkan (titik yang sama
  dengan kerangka tata letak worker), hanya dipanggil worker untuk user yang setuju saat saklar menyala.
- `correction_trigger` / `donate` (M1c, pre-flight A16 §2 "Trigger points", K3, G7): titik koreksi yang sudah ada
  (`record.mark_recorded`, `record.skip_item`, `record.choose_app`, bot "Nominal salah") memanggil `donate`; koreksi
  memindahkan `sample_lines` ke `proof_samples` (status `menunggu`), selain itu (bacaan benar, `batal`/`duplikat`,
  persetujuan ditarik, saklar mati) baris itu dikosongkan. Pembersihan umur sampel: `maintenance.purge_samples`.
- Tinjauan Admin (M1d, pre-flight A16 §2 "Admin review -> corpus", K4, K17): `approve_sample` (baris editan disamarkan
  lagi dan diperiksa `approved_lines`), `reject_sample` (menghapus baris: sampel `ditolak` tidak pernah ada),
  `delete_sample`, `read_lines` (pembaca sekarang tanpa aturan), `corpus_entry`, `truth_diff`/`gated_diff`/
  `confirmed_expect` (expect memakai nilai koreksi user; dipakai juga `kotak_corpus add --dari-donasi`), `pseudonym_ok`.
- `forget_user` (G4): persetujuan user, `proof_samples`-nya, dan `receipt_scans.sample_lines` miliknya. Hapus akun
  (`account_deletion.delete_account`) dan gabung akun (`merge.merge_users`, source; persetujuan tidak diwariskan ke
  target) menghapus SEMUA sampel; menarik persetujuan menyisakan sampel yang sudah `disetujui` (keputusan pemilik).
- Urutan kunci (review M1c temuan 1, 5): selalu baris persetujuan SEBELUM `receipt_scans`. `forget_user` menghapus
  persetujuan lebih dulu; pendonor yang mengunci baris item (lewati, jawaban aplikasi) mengambil kunci persetujuan
  (`lock_consent`) sebelum itu.

Tidak ada fungsi di sini yang meng-commit; pemanggil (route, hapus akun, gabung akun) meng-commit. Tidak ada cache. Modul ini tidak
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
from app.services.kotak_struk.readers.base import ParseContext, Secrets
from app.services.kotak_struk.readers.labels import WIB
from app.services.kotak_struk.readers.profiles import PROFILES
from app.services.kotak_struk.registry import looks_like_proof, read_document

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
# Review akhir A16 temuan 1: nomor yang terpecah. Baris yang hanya potongan 2-5 digit (boleh dipisah spasi/strip)
# langsung sesudah baris berakhiran label nomor ("No Rekening" / "1234" / "5678") dibuang saat penangkapan; baris
# editan Admin dengan >= SPLIT_NUMBER_DIGITS digit di luar rentang yang dibiarkan ("Ref 1234/5678/9012") ditolak.
SPLIT_NUMBER_DIGITS = 10
_NUMBER_LABEL_END = re.compile(
    r"(?<![^\W\d_])(?:rekening|rek|no|nomor|va|virtual\s+account|kartu|card|nik|hp|telp|telepon)\W*$", re.IGNORECASE)
_DIGIT_CHUNK = re.compile(r"\d[\d \-]*")


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


def _long_digits(line: str) -> bool:
    """Deret >= MIN_RUN_DIGITS digit di luar NMID publik (`ID` + >= 10 digit di baris berlabel NMID, rentang yang sama
    yang dibiarkan `samaran.mask_line`). Dipakai penangkapan dan persetujuan Admin, supaya baris NMID ikut tersimpan
    seperti `mask_line` membiarkannya (review akhir A16, verifikasi gelombang perbaikan)."""
    if samaran._NMID_LINE.search(line):
        line = samaran._NMID.sub(" ", line)
    return bool(_LONG_DIGITS.search(line))


def _grouped_account(line: str) -> bool:
    """Ada nomor berkelompok ribuan >= GROUPED_MIN_DIGITS digit yang tidak langsung sesudah Rp/IDR ("Rek 1.234.567.890":
    `mask_line` membiarkannya karena berbentuk nominal). "Rp 1.234.567" tetap."""
    for m in _GROUPED_NUMBER.finditer(line):
        if sum(c.isdigit() for c in m.group()) >= GROUPED_MIN_DIGITS and not _AFTER_CURRENCY.search(line[:m.start()]):
            return True
    return False


def _holds_secret(line: str, secrets: Secrets) -> bool:
    """Baris masih memuat nilai rahasia (nomor referensi, rekening, NMID di luar baris berlabel NMID), deret >= 6 digit
    (`_long_digits`: NMID publik di baris berlabel NMID tidak dihitung), alamat email, atau nomor berkelompok ribuan
    >= 10 digit di luar Rp/IDR (review M1b temuan 2, 3).

    Dua aturan terakhir (email, nomor berkelompok) juga harus diterapkan pemeriksaan persetujuan Admin (M1d) pada baris
    editan, bersama `\\d{6,}`."""
    if _long_digits(line) or _EMAIL.search(line) or _grouped_account(line):
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
    pengirim, merchant terbaca, user) -> baris yang masih memuat nilai `secrets` atau deret >= 6 digit dibuang, juga
    potongan nomor 2-5 digit sesaat sesudah baris berakhiran label nomor ("No Rekening" / "1234") -> paling
    banyak SAMPLE_MAX_LINES baris, masing-masing SAMPLE_LINE_MAX karakter. None juga bila tidak ada baris tersisa."""
    if doc.doc_type not in SAMPLE_TYPES and not looks_like_proof(TextDoc(lines=list(lines), kind=KIND_IMAGE)):
        return None
    clean = pc.clean_lines(lines)
    masked = [samaran.mask_line(line) for line in clean]
    named, _user = samaran.pseudonymise(masked, _known_names(clean, doc, user_name))
    kept: list[str] = []
    for line in named:
        if _holds_secret(line, secrets) or (kept and _number_chunk(line) and _NUMBER_LABEL_END.search(kept[-1])):
            continue
        kept.append(line[:SAMPLE_LINE_MAX])
    return kept[:SAMPLE_MAX_LINES] or None


def _number_chunk(line: str) -> bool:
    """Baris yang hanya potongan nomor 2-5 digit, boleh dipisah spasi/strip ("1234", "88 12", "3456-7")."""
    text = line.strip()
    return bool(_DIGIT_CHUNK.fullmatch(text)) and text[-1].isdigit() and 2 <= sum(c.isdigit() for c in text) <= 5


def _digits_outside_kept(line: str) -> int:
    """Jumlah digit desimal di luar rentang yang dibiarkan `samaran.mask_line` (nominal, tanggal, jam, NMID); penanda
    `…dddd` dihitung digitnya."""
    chars = list(line)
    for start, end in samaran._kept_spans(line):
        chars[start:end] = " " * (end - start)
    return sum(c.isdecimal() for c in chars)


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


# ── Tinjauan Admin -> entri korpus (M1d) ────────────────────────────────────

ST_SAMPLE_APPROVED = "disetujui"
SAMPLE_STATUSES = (ST_SAMPLE_WAITING, ST_SAMPLE_APPROVED, "ditolak")   # `ditolak` tidak pernah tersimpan (ruling M1d)
# Field koreksi user (`truth`) -> kunci `expect` korpus. `app` hanya untuk kunci profil (bukan `baru`).
TRUTH_FIELDS = ("total", "date", "status", "flow", "app")
_PROFILE_KEYS = frozenset(p.key for p in PROFILES)
_EXPECT_KEY = {"total": "total", "date": "paid_at", "status": "status", "flow": "flow", "app": "issuer"}
CORPUS_ID_PREFIX = "donasi-"


class SampleNotFound(LookupError):
    def __init__(self):
        super().__init__("Sampel tidak ditemukan")


class SampleConflict(Exception):
    """Status sampel tidak sesuai keputusan (sudah diputuskan, atau belum disetujui); pesannya aman ditampilkan."""


class SampleLineSecret(ValueError):
    """Baris editan pemilik masih memuat nomor/alamat yang tidak boleh masuk korpus; pesannya aman ditampilkan."""


class SampleNameNotPseudonym(ValueError):
    def __init__(self):
        super().__init__("Nama user harus nama samaran")


_PSEUDONYM_WORDS = frozenset(w.casefold() for name in samaran.PSEUDONYMS.values() for w in name.split())


def pseudonym_ok(name: str | None) -> bool:
    """Nama user sampel (masuk entri korpus publik) hanya kata nama samaran (`samaran.PSEUDONYMS`, huruf besar/kecil
    bebas); kosong boleh. Murni."""
    return not name or all(w.casefold() in _PSEUDONYM_WORDS for w in name.split())


def approved_lines(lines: list[str]) -> list[str]:
    """Baris editan pemilik yang siap disimpan: `samaran.mask_line` diterapkan lagi pada setiap baris, lalu aturan
    yang sama dengan penangkapan (`_holds_secret` tanpa nilai rahasia bukti, yang tidak lagi diketahui): deret >= 6 digit
    (`_long_digits`, NMID publik tidak dihitung), alamat email, nomor berkelompok ribuan >= 10 digit di luar Rp/IDR, atau
    >= SPLIT_NUMBER_DIGITS digit di luar rentang yang dibiarkan (nominal, tanggal, jam, NMID; nomor terpecah
    "Ref 1234/5678/9012") -> `SampleLineSecret` dengan nomor baris (mulai 1). Murni."""
    masked = [samaran.mask_line(line) for line in lines]
    for i, line in enumerate(masked, 1):
        if _long_digits(line):
            raise SampleLineSecret(f"Masih ada nomor panjang di baris {i}")
        if _EMAIL.search(line):
            raise SampleLineSecret(f"Masih ada alamat email di baris {i}")
        if _grouped_account(line):
            raise SampleLineSecret(f"Masih ada nomor rekening di baris {i}")
        if _digits_outside_kept(line) >= SPLIT_NUMBER_DIGITS:   # "Ref 1234/5678/9012" (review akhir A16 temuan 1)
            raise SampleLineSecret(f"Masih ada nomor panjang di baris {i}")
    return masked


async def get_sample(db: AsyncSession, sample_id: uuid.UUID) -> ProofSample:
    sample = (await db.execute(select(ProofSample).where(ProofSample.id == sample_id))).scalar_one_or_none()
    if sample is None:
        raise SampleNotFound()
    return sample


async def _missing_or_conflict(db: AsyncSession, sample_id: uuid.UUID, message: str):
    if (await db.execute(select(exists().where(ProofSample.id == sample_id)))).scalar():
        raise SampleConflict(message)
    raise SampleNotFound()


async def approve_sample(db: AsyncSession, sample_id: uuid.UUID, *, lines: list[str], by: uuid.UUID, now: datetime,
                         note: str | None = None, user_name: str | None = None, set_user_name: bool = False
                         ) -> ProofSample:
    """Setujui sampel `menunggu` dengan baris editan pemilik (`approved_lines`: disamarkan lagi, nomor/email tersisa ->
    `SampleLineSecret`, tanpa perubahan apa pun). `set_user_name`: nama samaran user diganti `user_name` (None =
    dikosongkan); selain itu yang tersimpan tetap. UPDATE bersyarat status `menunggu` (dua keputusan bersamaan tidak
    saling menimpa); bukan `menunggu` -> `SampleConflict`, tidak ada -> `SampleNotFound`. Tidak meng-commit."""
    if set_user_name and not pseudonym_ok(user_name):
        raise SampleNameNotPseudonym()
    masked = approved_lines(lines)
    values = {"lines": masked, "status": ST_SAMPLE_APPROVED, "decided_at": now, "decided_by": by, "note": note}
    if set_user_name:
        values["user_name"] = user_name
    res = await db.execute(
        update(ProofSample).where(ProofSample.id == sample_id, ProofSample.status == ST_SAMPLE_WAITING)
        .values(**values).execution_options(synchronize_session=False))
    if (res.rowcount or 0) != 1:
        await _missing_or_conflict(db, sample_id, "Sampel sudah diputuskan")
    sample = await get_sample(db, sample_id)
    await db.refresh(sample)
    return sample


async def reject_sample(db: AsyncSession, sample_id: uuid.UUID) -> None:
    """Tolak sampel `menunggu` = hapus barisnya (G2, ruling M1d: tidak ada isi yang disimpan; sampel `ditolak` tidak
    pernah ada). Bukan `menunggu` -> `SampleConflict`, tidak ada -> `SampleNotFound`. Tidak meng-commit."""
    res = await db.execute(delete(ProofSample).where(ProofSample.id == sample_id,
                                                     ProofSample.status == ST_SAMPLE_WAITING))
    if (res.rowcount or 0) != 1:
        await _missing_or_conflict(db, sample_id, "Sampel sudah diputuskan")


async def delete_sample(db: AsyncSession, sample_id: uuid.UUID) -> None:
    """Hapus sampel status apa pun (sesudah entri disalin ke korpus); tidak ada -> `SampleNotFound`. Tidak meng-commit."""
    res = await db.execute(delete(ProofSample).where(ProofSample.id == sample_id))
    if (res.rowcount or 0) != 1:
        raise SampleNotFound()


def expect_from(doc) -> dict:
    """Hasil pembaca dalam bentuk `expect` korpus (urutan kunci seperti spec §7a). Dipindah dari
    `app/scripts/kotak_corpus.py` (diekspor ulang di sana) supaya Admin dan `add` memakai satu bentuk."""
    paid_at = doc.paid_at
    if paid_at is not None:
        paid_at = (paid_at.astimezone(WIB) if paid_at.tzinfo else paid_at.replace(tzinfo=WIB)).isoformat(timespec="seconds")
    return {
        "doc_type": doc.doc_type, "issuer": doc.issuer or None, "total": doc.amounts.total, "paid_at": paid_at,
        "counterparty": doc.counterparty.name or None, "status": doc.status, "flow": doc.flow,
    }


async def read_lines(lines: list[str], *, today: date, user_name: str | None) -> dict:
    """Pembaca SEKARANG pada baris sampel, TANPA aturan belajar, dalam bentuk `expect`: konteks seperti
    `kotak_corpus.sample_context` (`today` sampel, nama samaran user) dan pembacaan seperti `kotak_corpus.eval`
    (`kind` gambar, saklar bukti menyala). Hasilnya sama dengan `expect` yang dihitung `add --dari-donasi`."""
    res = await read_document(TextDoc(lines=list(lines), kind=KIND_IMAGE),
                              ParseContext(today=today, user_name=user_name), proofs_enabled=True)
    return expect_from(res.parsed.doc)


def _wib_day(paid_at) -> str | None:
    if not isinstance(paid_at, str) or not paid_at:
        return None
    try:
        moment = datetime.fromisoformat(paid_at)
    except ValueError:
        return None
    return (moment.astimezone(WIB).date() if moment.tzinfo else moment.date()).isoformat()


def _truth_value(field: str, truth: dict):
    value = truth.get(field)
    if field == "app" and value not in _PROFILE_KEYS:
        return None   # `baru` atau isian rusak: tidak ada penerbit yang bisa dipastikan
    return value


def truth_diff(expect: dict, truth: dict | None) -> list[tuple[str, object, object]]:
    """Beda koreksi user (`truth`, G7) dengan hasil pembaca (`expect`): `(field, koreksi, terbaca)` untuk total, tanggal
    (hari WIB `paid_at`), status, arah, dan aplikasi (`issuer`, hanya kunci profil), bila `truth` memuatnya (bukan
    None). Murni."""
    truth = truth if isinstance(truth, dict) else {}
    expect = expect if isinstance(expect, dict) else {}
    out = []
    for field in TRUTH_FIELDS:
        want = _truth_value(field, truth)
        if want is None:
            continue
        got = _wib_day(expect.get("paid_at")) if field == "date" else expect.get(_EXPECT_KEY[field])
        if want != got:
            out.append((field, want, got))
    return out


def gated_diff(expect: dict, truth: dict | None) -> list[str]:
    """Field yang berbeda antara koreksi user dan pembaca (ruling M1d fix 1: semua field, juga arah). `expect` entri
    memakai nilai koreksi user (`confirmed_expect`), jadi sampel `reviewed: true` seperti itu membuat gerbang rilis
    (`test_real_corpus_meets_release_gate`) merah sampai pembaca diperbaiki (K17): ditahan `reviewed: false`."""
    return [f for f, _want, _got in truth_diff(expect, truth)]


def _with_day(paid_at, day: str) -> str:
    """`paid_at` dengan tanggal WIB `day` (jam dari pembaca bila ada, selain itu 00:00 WIB)."""
    try:
        moment = datetime.fromisoformat(paid_at) if isinstance(paid_at, str) and paid_at else None
    except ValueError:
        moment = None
    new_day = date.fromisoformat(day)
    if moment is None:
        return datetime(new_day.year, new_day.month, new_day.day, tzinfo=WIB).isoformat(timespec="seconds")
    moment = moment.astimezone(WIB) if moment.tzinfo else moment.replace(tzinfo=WIB)
    return moment.replace(year=new_day.year, month=new_day.month, day=new_day.day).isoformat(timespec="seconds")


def confirmed_expect(expect: dict, truth: dict | None) -> dict:
    """`expect` dengan nilai koreksi user yang dipastikan pemilik (`truth` bukan None) menggantikan hasil pembaca: total,
    tanggal (`paid_at`, jam dari pembaca), status, arah, aplikasi (`issuer`, hanya kunci profil). Urutan kunci tetap.
    Murni."""
    out = dict(expect)
    for field, want, _got in truth_diff(expect, truth):
        key = _EXPECT_KEY[field]
        out[key] = _with_day(expect.get("paid_at"), want) if field == "date" else want
    return out


def corpus_entry(sample: ProofSample, expect: dict) -> dict:
    """Entri korpus dari sampel yang disetujui (urutan kunci fixture): `id` = `donasi-<doc_type>-<8 hex id sampel>`,
    `real`/`reviewed` true (pemilik sudah meninjau), `today`, `user_name` (nama samaran; tidak ada bila kosong),
    `lines`, `expect` (pembaca sekarang). Tanpa id user/item."""
    entry = {"id": f"{CORPUS_ID_PREFIX}{sample.doc_type or 'bukti'}-{sample.id.hex[:8]}", "real": True,
             "reviewed": True, "today": sample.today.isoformat()}
    if sample.user_name:
        entry["user_name"] = sample.user_name
    entry["lines"] = list(sample.lines or [])
    entry["expect"] = expect
    return entry
