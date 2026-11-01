"""Belajar lintas user dari koreksi bukti bayar Kotak Struk (spec 2026-11-01 §2-§4, §8, §12.1; pre-flight K3, K5, K7,
K9, G3, G5, G7).

Alur: user mencatat bukti (web: kartu bukti, form Catat; bot: tombol amplop) -> `record.mark_recorded` memanggil
`learn_from_correction` dengan nilai akhir TRANSAKSI yang tercatat (`Final`) -> nilai akhir dibandingkan dengan hasil
baca (`receipt_scans.document`, `merchant`) dan dicocokkan dengan kerangka tata letak (`receipt_scans.layout`,
kotak_struk/kerangka.py) -> paling banyak satu suara per jenis (`proof_rule_votes`, satu per user per aturan) ->
`proof_rules` dihitung ulang; mulai RULE_MIN_USERS (2) user berbeda aturan dibuat berstatus `menunggu`, dan hanya
keputusan pemilik di Admin (`decide`) yang mengubah statusnya.

Jenis aturan tahap 1 (K7): `label_total`, `label_pihak`, `label_tanggal`. Kunci aturan = kunci kerangka, tahap 1 hanya
kunci profil aplikasi yang dikenal (`gopay`, `jago`, ...); kunci `logo:<kata>` ditolak di sini juga (bisa nama orang;
tahap 2 M2 membukanya bersama pemeriksaannya). Nilai aturan = label kosakata dari kerangka: hanya baris BERLABEL, tanpa
`#` (digit tersamar), lolos `kerangka.safe_label` lagi. Nama, nomor, nominal, dan tanggal tidak pernah masuk tabel; nama
hanya dicocokkan lewat HMAC.

- `label_total`: nominal akhir berbeda dari total terbaca (juga bila total tidak terbaca) dan tercetak di baris
  `nominal` berlabel. Label biaya/potongan/saldo (`NOT_TOTAL_WORDS`) tidak pernah menjadi label total. Tepat satu label
  -> suara; beberapa -> label berkata awal "total" bila tepat satu; selain itu tanpa suara (G3). Nominal ketikan yang
  tidak tercetak tidak bisa dipelajari. Bukan suara juga (review L2 M-4): label sub-nominal (jumlah/nominal/amount tanpa
  "total") pada bukti yang punya baris biaya berlabel: user memilih mencatat tanpa biaya, bukan pembacaan yang salah.
- `label_pihak`: keterangan akhir memuat nama (n-gram 1-6 kata, HMAC) yang tercetak di baris `nama` berlabel PENERIMA
  (`_party_label`: ada kata penerima seperti penerima/ke/tujuan/merchant/toko/nama, dan tanpa kata bukan-penerima seperti
  keterangan/berita/status/metode/sumber/dari/pengirim; review L2 I-1: keterangan transfer yang diketik ulang sebagai
  deskripsi bukan koreksi nama), dan nama itu bukan nama yang terbaca (juga bukan potongan nama terbaca: "Budi" dari
  "BUDI SANTOSO") (K5). Nama panggilan yang tidak tercetak tidak pernah cocok.
- `label_tanggal`: tanggal akhir bukan tanggal bukti (WIB dari `paid_at`) dan bukan hari ini, tercetak di baris
  `tanggal` berlabel (K9; dalam praktik hanya dari form Catat).

Belajar itu bonus: `learn_from_correction` tidak pernah melempar (galat -> log + 0), menulis di SAVEPOINT sendiri,
tidak meng-commit, dan tidak menyentuh item maupun transaksi. Status item, `check_recordable`, klaim, dan dedup tidak
pernah membaca tabel ini. Hapus akun dan gabung akun memanggil `forget_user` (suara dihapus, aturan dihitung ulang).
Rumah tangga suara = `item.household_id` (layanan ini tidak menanyakan keanggotaan household sendiri).

Hitungan `recount` dibaca di snapshot transaksi pemanggil: dua suara pertama dalam transaksi yang tumpang tindih bisa
sama-sama melihat 1 user (aturan tidak dibuat), dan dua pembuat bersamaan bisa menyimpan hitungan lama (review L2 M-2).
`reconcile_rules` menghitung ulang semuanya dari tabel suara dan dijalankan tiap jam oleh `kotak_maintenance`.

Pembaca (L3): worker memuat aturan `disetujui` lewat `approved_rules` (cache modul RULE_CACHE_S detik) ke
`ParseContext.rules`; pembaca QRIS/transfer/tidak dikenali mengambil labelnya dengan `learned_for` (= `profiles.learned_for`,
di modul pembaca supaya pembaca tidak mengimpor modul database ini).

Untuk API Admin (L4a): catatan keputusan dibatasi 200 karakter di model permintaan (`note` String(200); `decide` tidak
memotongnya), `RuleNotFound` -> 404 dan `RuleConflict` -> 409 dengan teks pengecualiannya (MSG_RULE_*), dan sesudah
`decide` pemanggil meng-commit LALU memanggil `invalidate_rules_cache()` (L3), supaya pembaca tidak memuat ulang cache
dari status lama.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Iterator

from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ProofRule, ProofRuleVote
from app.services.kotak_struk.config import LAYOUT_LABEL_MAX, LAYOUT_TYPES, RULE_CACHE_S, RULE_MIN_USERS
from app.services.kotak_struk.kerangka import safe_label
from app.services.kotak_struk.merchants import hmac_hex, normalize_name
from app.services.kotak_struk.readers.labels import WIB
from app.services.kotak_struk.readers.profiles import PROFILES, Learned, learned_for  # noqa: F401 (diekspor ulang, L3)

log = logging.getLogger(__name__)

KIND_TOTAL = "label_total"
KIND_PIHAK = "label_pihak"
KIND_TANGGAL = "label_tanggal"
KINDS = (KIND_TOTAL, KIND_PIHAK, KIND_TANGGAL)

ST_MENUNGGU = "menunggu"
ST_DISETUJUI = "disetujui"
ST_DITOLAK = "ditolak"
ST_DICABUT = "dicabut"
RULE_STATUSES = (ST_MENUNGGU, ST_DISETUJUI, ST_DITOLAK, ST_DICABUT)

# Keputusan admin (G5): aksi -> (status baru, status asal yang boleh). Selain itu 409.
DECISIONS: dict[str, tuple[str, frozenset[str]]] = {
    "setujui": (ST_DISETUJUI, frozenset({ST_MENUNGGU, ST_DITOLAK, ST_DICABUT})),
    "tolak": (ST_DITOLAK, frozenset({ST_MENUNGGU})),
    "cabut": (ST_DICABUT, frozenset({ST_DISETUJUI})),
}
MSG_RULE_NOT_FOUND = "Aturan tidak ditemukan"
MSG_RULE_CONFLICT = "Aturan ini tidak bisa diubah ke status itu"

KEY_MAX = 60                 # panjang kolom rule_key / value
NAME_NGRAM_MAX = 6           # kata nama terpanjang (sama dengan kerangka.NAME_MAX_WORDS)
DESCRIPTION_WORDS_MAX = 40   # kata keterangan yang dicocokkan (keterangan transaksi pendek)
_PROFILE_KEYS = frozenset(p.key for p in PROFILES)

# `label_pihak` hanya untuk label yang menamai penerima (review L2 I-1). Kata label sudah huruf kecil (`safe_label`).
PARTY_WORDS = frozenset({"penerima", "ke", "kepada", "tujuan", "merchant", "toko", "nama", "name", "recipient", "to",
                         "payee"})
NOT_PARTY_WORDS = frozenset({"status", "keterangan", "catatan", "berita", "pesan", "deskripsi", "metode", "sumber",
                             "dari", "pengirim", "from", "sender", "lokasi", "location", "alamat", "id", "ref", "kode",
                             "cabang"})
# `label_total`: label biaya/potongan/saldo tidak pernah label total; label sub-nominal + baris biaya = tanpa biaya.
NOT_TOTAL_WORDS = frozenset({"biaya", "admin", "fee", "diskon", "potongan", "cashback", "pajak", "saldo"})
SUB_AMOUNT_WORDS = frozenset({"jumlah", "nominal", "amount"})
FEE_WORDS = frozenset({"biaya", "admin", "fee"})


@dataclass(frozen=True)
class Final:
    """Nilai akhir yang tercatat (dari baris `transactions`); `today` = hari ini WIB saat mencatat."""
    amount: int | None
    txn_date: date | None
    description: str | None
    today: date


@dataclass(frozen=True)
class Vote:
    kind: str
    rule_key: str
    value: str


class RuleNotFound(LookupError):
    """Aturan dengan id itu tidak ada (404)."""


class RuleConflict(ValueError):
    """Aksi tidak sah untuk status aturan saat ini (409)."""


def today_wib() -> date:
    """Hari ini menurut WIB (sama dengan worker: `ParseContext.today`)."""
    return datetime.now(WIB).date()


# ── suara (murni) ───────────────────────────────────────────────────────────

def _votable(label) -> bool:
    """Label kerangka yang boleh menjadi nilai aturan: ada, tanpa `#` (digit), <= LAYOUT_LABEL_MAX, dan tetap sama
    sesudah `safe_label` (kosakata label, tanpa digit). Kerangka sudah aman; ini pagar kedua."""
    return (isinstance(label, str) and bool(label) and "#" not in label and len(label) <= LAYOUT_LABEL_MAX
            and safe_label(label, forbidden_words=set()) == label)


def _valid_key(key) -> bool:
    """Tahap 1: hanya kunci profil aplikasi (review L2 M-1). Kunci `logo:<kata>` bisa memuat nama orang; M2 membukanya
    lagi bersama pemeriksaan logo di sini."""
    return isinstance(key, str) and len(key) <= KEY_MAX and key in _PROFILE_KEYS


def _words(label: str) -> set[str]:
    return set(label.split())


def _party_label(label: str) -> bool:
    """Label yang menamai penerima: ada kata PARTY_WORDS dan tanpa kata NOT_PARTY_WORDS."""
    words = _words(label)
    return bool(words & PARTY_WORDS) and not words & NOT_PARTY_WORDS


def _fee_dropped(label: str, layout: dict) -> bool:
    """Label sub-nominal (jumlah/nominal/amount tanpa "total") pada bukti dengan baris biaya berlabel: nominal itu
    dipilih user tanpa biaya, bukan total yang salah baca (review L2 M-4)."""
    words = _words(label)
    if not words & SUB_AMOUNT_WORDS or "total" in words:
        return False
    return any(_words(e["label"]) & FEE_WORDS for e in _entries(layout, "nominal"))


def _entries(layout: dict, kind: str) -> Iterator[dict]:
    """Baris kerangka berjenis `kind` dengan label yang boleh menjadi suara (baris tanpa label = derau, dilewati)."""
    for entry in layout.get("lines") or ():
        if isinstance(entry, dict) and entry.get("kind") == kind and _votable(entry.get("label")):
            yield entry


def _one_label(labels: set[str], *, prefer_total: bool = False) -> str | None:
    """Tepat satu label berbeda -> label itu. Beberapa: (nominal saja) label berkata awal "total" bila tepat satu.
    Selain itu None (G3)."""
    if len(labels) == 1:
        return next(iter(labels))
    if prefer_total:
        totals = [label for label in labels if label.split()[0] == "total"]
        if len(totals) == 1:
            return totals[0]
    return None


def _doc_date(document: dict) -> date | None:
    """Tanggal bukti: tanggal WIB dari `paid_at` dokumen (sama dengan `parsed_date` worker)."""
    raw = document.get("paid_at")
    if not raw:
        return None
    try:
        paid = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return paid.astimezone(WIB).date() if paid.tzinfo else paid.date()


def _ngrams(words: list[str], longest: int) -> Iterator[str]:
    for n in range(1, min(longest, len(words)) + 1):
        for i in range(len(words) - n + 1):
            yield " ".join(words[i:i + n])


def votes_for(layout: dict | None, document: dict | None, merchant: str | None, final: Final) -> list[Vote]:
    """Suara dari satu pencatatan (lihat docstring modul): paling banyak satu per jenis, urut label_total,
    label_pihak, label_tanggal. Murni (hanya HMAC). Kerangka tanpa kunci yang sah, rusak, atau kosong -> []."""
    if not isinstance(layout, dict) or not _valid_key(layout.get("key")):
        return []
    key = layout["key"]
    document = document if isinstance(document, dict) else {}
    votes: list[Vote] = []

    amounts = document.get("amounts") if isinstance(document.get("amounts"), dict) else {}
    if final.amount is not None and final.amount != amounts.get("total"):
        label = _one_label({e["label"] for e in _entries(layout, "nominal")
                            if e.get("amount") == final.amount and not _words(e["label"]) & NOT_TOTAL_WORDS},
                           prefer_total=True)
        if label and not _fee_dropped(label, layout):
            votes.append(Vote(KIND_TOTAL, key, label))

    words = normalize_name(final.description).split()[:DESCRIPTION_WORDS_MAX]
    if words:
        counterparty = document.get("counterparty") if isinstance(document.get("counterparty"), dict) else {}
        read_words = normalize_name(counterparty.get("name") or merchant).split()
        # Nama terbaca dan setiap potongannya bukan koreksi (baris yang mencetak nama terbaca tidak pernah cocok).
        read_grams = set(_ngrams(read_words, len(read_words)))
        typed = {hmac_hex(gram) for gram in _ngrams(words, NAME_NGRAM_MAX) if gram not in read_grams}
        label = _one_label({e["label"] for e in _entries(layout, "nama")
                            if e.get("h") in typed and _party_label(e["label"])})
        if label:
            votes.append(Vote(KIND_PIHAK, key, label))

    day = final.txn_date
    if day is not None and day != final.today and day != _doc_date(document):
        label = _one_label({e["label"] for e in _entries(layout, "tanggal") if e.get("date") == day.isoformat()})
        if label:
            votes.append(Vote(KIND_TANGGAL, key, label))
    return votes


# ── suara dan aturan (database) ─────────────────────────────────────────────

async def recount(db: AsyncSession, kind: str, rule_key: str, value: str) -> ProofRule | None:
    """Hitung ulang pendukung satu aturan: `users` = suara (satu per user), `households` = rumah tangga berbeda (NULL
    tidak dihitung). Baris aturan dibuat berstatus `menunggu` saat `users >= RULE_MIN_USERS`; baris yang ada hanya
    diperbarui hitungannya (status apa pun, juga turun di bawah ambang) dan tidak pernah dihapus. None bila belum ada
    aturan. Tidak meng-commit."""
    users, households = (await db.execute(
        select(func.count(), func.count(distinct(ProofRuleVote.household_id)))
        .where(ProofRuleVote.kind == kind, ProofRuleVote.rule_key == rule_key, ProofRuleVote.value == value)
    )).one()
    match = (ProofRule.kind == kind, ProofRule.rule_key == rule_key, ProofRule.value == value)
    rule_id = (await db.execute(select(ProofRule.id).where(*match))).scalar_one_or_none()
    if rule_id is None:
        if users < RULE_MIN_USERS:
            return None
        # Dua penghitung bersamaan: yang kedua memperbarui hitungan baris yang baru dibuat (status tetap).
        await db.execute(
            pg_insert(ProofRule)
            .values(id=uuid.uuid4(), kind=kind, rule_key=rule_key, value=value, users=users, households=households,
                    status=ST_MENUNGGU)
            .on_conflict_do_update(index_elements=["kind", "rule_key", "value"],
                                   set_={"users": users, "households": households})
        )
    else:
        await db.execute(update(ProofRule).where(ProofRule.id == rule_id)
                         .values(users=users, households=households)
                         .execution_options(synchronize_session=False))
    return (await db.execute(select(ProofRule).where(*match).execution_options(populate_existing=True))).scalar_one()


async def record_votes(db: AsyncSession, votes: Iterable[Vote], *, user_id: uuid.UUID,
                       household_id: uuid.UUID | None) -> None:
    """Simpan suara user (sekali per user per aturan: suara ulang diabaikan, rumah tangga suara pertama tetap), lalu
    `recount` tiap aturan. Tidak meng-commit."""
    for vote in dict.fromkeys(votes):
        await db.execute(
            pg_insert(ProofRuleVote)
            .values(kind=vote.kind, rule_key=vote.rule_key, value=vote.value, user_id=user_id,
                    household_id=household_id)
            .on_conflict_do_nothing()
        )
        await recount(db, vote.kind, vote.rule_key, vote.value)


async def learn_from_correction(db: AsyncSession, item, final: Final, *, user_id: uuid.UUID) -> int:
    """Suara dari pencatatan item Kotak Struk `item` dengan nilai akhir `final`; jumlah suara yang dicatat. Tidak jalan
    bila `item.layout` kosong atau `item.doc_type` bukan LAYOUT_TYPES (struk belanja tidak pernah). Tulisan di
    SAVEPOINT sendiri; tidak meng-commit (pemanggil meng-commit bersama penandaan item); tidak menyentuh item atau
    transaksi. Tidak pernah melempar: galat -> log peringatan + 0, savepoint dibatalkan, sesi pemanggil tetap utuh."""
    item_id = getattr(item, "id", None)
    try:
        if not item.layout or item.doc_type not in LAYOUT_TYPES:
            return 0
        votes = votes_for(item.layout, item.document, item.merchant, final)
        if not votes:
            return 0
        async with db.begin_nested():
            await record_votes(db, votes, user_id=user_id, household_id=item.household_id)
        return len(votes)
    except Exception:
        log.warning("suara koreksi untuk item Kotak Struk %s tidak dicatat", item_id, exc_info=True)
        return 0


async def reconcile_rules(db: AsyncSession) -> int:
    """Samakan `proof_rules` dengan tabel suara (review L2 M-2): aturan yang hitungannya beda dihitung ulang, dan suara
    >= RULE_MIN_USERS user tanpa baris aturan mendapat aturan `menunggu` (`recount`). Status tidak pernah diubah, baris
    tidak pernah dihapus. Idempoten; jumlah aturan yang dibuat/diperbaiki. Tidak meng-commit (pemanggil: pemeliharaan
    tiap jam, `maintenance.reconcile_proof_rules`)."""
    counted = {(kind, rule_key, value): (users, households) for kind, rule_key, value, users, households in (
        await db.execute(
            select(ProofRuleVote.kind, ProofRuleVote.rule_key, ProofRuleVote.value, func.count(),
                   func.count(distinct(ProofRuleVote.household_id)))
            .group_by(ProofRuleVote.kind, ProofRuleVote.rule_key, ProofRuleVote.value)
        )).all()}
    stored = {(kind, rule_key, value): (users, households) for kind, rule_key, value, users, households in (
        await db.execute(select(ProofRule.kind, ProofRule.rule_key, ProofRule.value, ProofRule.users,
                                ProofRule.households))).all()}
    fixes = sorted(key for key in counted.keys() | stored.keys()
                   if counted.get(key, (0, 0)) != stored.get(key)
                   and (key in stored or counted[key][0] >= RULE_MIN_USERS))
    for key in fixes:
        await recount(db, *key)
    return len(fixes)


async def forget_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Lupakan semua suara user (hapus akun, gabung akun; G7): suara dihapus lalu setiap aturan yang pernah dipilihnya
    dihitung ulang (status tidak berubah, baris aturan tidak dihapus). Tidak meng-commit."""
    keys = (await db.execute(
        select(ProofRuleVote.kind, ProofRuleVote.rule_key, ProofRuleVote.value).where(ProofRuleVote.user_id == user_id)
    )).all()
    await db.execute(delete(ProofRuleVote).where(ProofRuleVote.user_id == user_id))
    for kind, rule_key, value in keys:
        await recount(db, kind, rule_key, value)


# ── keputusan admin (G5) ────────────────────────────────────────────────────

def next_status(current: str | None, action: str) -> str | None:
    """Status sesudah `action` (setujui | tolak | cabut) dari `current`, atau None bila transisinya tidak sah."""
    decision = DECISIONS.get(action)
    if decision is None or current not in decision[1]:
        return None
    return decision[0]


async def decide(db: AsyncSession, rule_id: uuid.UUID, action: str, *, by: uuid.UUID | None, note: str | None,
                 now: datetime) -> ProofRule:
    """Keputusan admin atas satu aturan: UPDATE bersyarat (status asal yang sah, G5), jadi dua keputusan bersamaan
    tidak saling menimpa diam-diam. Mengisi `decided_at`, `decided_by`, `note`. `RuleNotFound` bila id tidak ada,
    `RuleConflict` bila transisinya tidak sah. Tidak meng-commit; pemanggil juga membatalkan cache aturan."""
    decision = DECISIONS.get(action)
    if decision is not None:
        status, allowed = decision
        done = await db.execute(
            update(ProofRule).where(ProofRule.id == rule_id, ProofRule.status.in_(allowed))
            .values(status=status, decided_at=now, decided_by=by, note=note)
            .execution_options(synchronize_session=False)
        )
        if done.rowcount == 1:
            return (await db.execute(select(ProofRule).where(ProofRule.id == rule_id)
                                     .execution_options(populate_existing=True))).scalar_one()
    if (await db.execute(select(ProofRule.id).where(ProofRule.id == rule_id))).scalar_one_or_none() is None:
        raise RuleNotFound(MSG_RULE_NOT_FOUND)
    raise RuleConflict(MSG_RULE_CONFLICT)


# ── aturan yang disetujui untuk pembaca (L3) ────────────────────────────────

_clock = time.monotonic          # diganti tes
_rules_cache: tuple[float, dict] | None = None   # (waktu muat, aturan)
_rules_generation = 0            # naik tiap invalidate: muatan yang dimulai sebelumnya tidak disimpan


def invalidate_rules_cache() -> None:
    """Buang cache aturan (API Admin memanggilnya SESUDAH commit keputusan): pembacaan berikutnya memuat ulang."""
    global _rules_cache, _rules_generation
    _rules_cache = None
    _rules_generation += 1


def _copy_rules(rules: dict) -> dict[str, dict[str, list[str]]]:
    return {key: {kind: list(values) for kind, values in kinds.items()} for key, kinds in rules.items()}


async def approved_rules(db: AsyncSession) -> dict[str, dict[str, list[str]]]:
    """Aturan berstatus `disetujui` untuk pembaca: `{rule_key: {"label_total": [...], "label_pihak": [...],
    "label_tanggal": [...]}}`, label urut pendukung (`users`) terbanyak, lalu yang lebih dulu disetujui (`decided_at`),
    lalu teksnya. Cache modul RULE_CACHE_S detik (jam monotonic); `invalidate_rules_cache` membuangnya. Galat database:
    log peringatan dan `{}` (pembaca tetap jalan tanpa aturan; tidak disimpan di cache, jadi dicoba lagi), kueri di
    SAVEPOINT sendiri supaya sesi pemanggil tetap bisa dipakai. Tidak meng-commit."""
    global _rules_cache
    cached = _rules_cache
    if cached is not None and _clock() - cached[0] < RULE_CACHE_S:
        return _copy_rules(cached[1])
    generation = _rules_generation
    try:
        async with db.begin_nested():
            rows = (await db.execute(
                select(ProofRule.rule_key, ProofRule.kind, ProofRule.value)
                .where(ProofRule.status == ST_DISETUJUI, ProofRule.kind.in_(KINDS))
                .order_by(ProofRule.users.desc(), ProofRule.decided_at.asc(), ProofRule.value.asc())
            )).all()
    except Exception:
        log.warning("aturan belajar Kotak Struk tidak bisa dimuat; bukti dibaca tanpa aturan", exc_info=True)
        return {}
    rules: dict[str, dict[str, list[str]]] = {}
    for rule_key, kind, value in rows:
        rules.setdefault(rule_key, {k: [] for k in KINDS})[kind].append(value)
    if generation == _rules_generation:
        _rules_cache = (_clock(), rules)
    return _copy_rules(rules)
