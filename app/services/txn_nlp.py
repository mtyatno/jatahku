"""Shared transaction NLP: keyword extraction, category guessing, per-user
learned keyword matching. Used by both the Telegram bot and the web API so the
two channels share one classification + learning implementation.

Plugin R7 (ADR-P5, 05-desain-buku-usaha.md B3.2): urutan cocok `cari_amplop` = kata user sendiri (amplop ruang ini) →
kamus ruang (`RuangKamus`, hanya ruang usaha) → kamus kategori Fitur Tambahan (H2, titik `nlp_kamus`) → kamus
kategori → nama amplop. Kamus ruang hanya dibaca untuk ruang `usaha` yang sedang dicari dan hanya ditulis dari catatan
web bukan-privat ke amplop bersama ruang usaha (`save_learned_keywords(kamus_ruang=True)`); ruang keluarga dan bot tidak
pernah memakainya (AGENTS.md aturan 8)."""
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select

STOPWORDS = {"di", "ke", "dari", "yang", "dan", "untuk", "dengan", "ya", "aku",
             "saya", "kamu", "ini", "itu", "ada", "buat", "sama", "juga", "mau",
             "beli", "bayar", "beli", "tadi", "lagi", "udah", "sudah", "pas", "aja"}

CATEGORY_KEYWORDS = {
    "makan": ["makan", "nasi", "ayam", "sate", "bakso", "mie", "noodle", "rice",
              "lunch", "dinner", "breakfast", "sarapan", "siang", "malam",
              "warteg", "padang", "resto", "restaurant", "cafe", "kafe",
              "kopi", "coffee", "starbucks", "mcd", "kfc", "pizza",
              "gofood", "grabfood", "shopeefood", "snack", "jajan",
              "soto", "martabak", "seblak"],
    "transport": ["grab", "gojek", "ojek", "taxi", "bensin", "parkir",
                  "tol", "busway", "mrt", "krl", "kereta", "bus",
                  "transport", "uber", "maxim", "indriver",
                  "spbu", "pertamina", "shell", "bengkel"],
    "hiburan": ["nonton", "film", "bioskop", "game", "steam", "netflix",
                "spotify", "youtube", "premium", "langganan", "subscribe",
                "hangout", "karaoke", "mall"],
    "belanja": ["baju", "pakaian", "fashion", "kaos", "celana", "jaket", "kemeja", "dress",
                "sepatu", "sandal", "tas", "dompet", "aksesoris", "jam tangan",
                "shopee", "tokped", "tokopedia", "lazada", "tiktok shop", "belanja", "online", "shop"],
    "tagihan": ["listrik", "air", "pdam", "internet", "wifi", "pulsa",
                "token", "indihome", "telkom", "pln"],
    "kesehatan": ["apotek", "apotik", "klinik", "kimia farma", "k24"],
}


PURPOSE_KEYWORDS = {
    "saving": ["tabungan", "nikah", "darurat", "liburan", "umroh",
               "rumah", "mobil", "motor", "pendidikan", "sekolah",
               "kuliah", "dp", "menikah", "haji", "investasi", "pensiun",
               "dana darurat", "dp rumah", "dp mobil"],
    "sinking_fund": ["servis", "pajak", "asuransi", "perpanjang",
                     "tahunan", "semester", "langganan", "renewal",
                     "hosting", "domain", "stnk", "bpjs", "ppn",
                     "service", "maintenance", "perawatan"],
}


def guess_purpose(name: str) -> str:
    """Suggest envelope purpose from name. Returns 'expense' as default."""
    name_lower = name.lower()
    for purpose, keywords in PURPOSE_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return purpose
    return "expense"


def extract_keywords(description: str) -> list:
    import re as _re
    words = _re.sub(r'[^\w\s]', '', description.lower()).split()
    keywords = [w for w in words if len(w) >= 3 and w not in STOPWORDS]
    # Also include full cleaned phrase for exact future matches
    phrase = " ".join(keywords)
    if phrase and phrase not in keywords:
        keywords.append(phrase)
    return keywords


# Kamus ruang (R7): token nominal/angka bukan kata ("125rb", "50", "rp17.000"); kunci kolom maksimal 100 huruf;
# paling banyak `KATA_JUMLAH` kata per keterangan (satu kueri `IN`, satu upsert per kata).
_NOMINAL = re.compile(r"^(rp)?\d+([.,]\d+)*(rb|ribu|k|jt|juta|pcs|kg|gr|pax)?$")
_SATUAN = {"pcs", "pax", "kg", "gram", "ltr", "liter", "buah", "biji", "porsi", "lusin", "unit"}
KATA_MAKS = 100
KATA_JUMLAH = 12

SUMBER_KATA_SAYA = "kata_saya"
SUMBER_KAMUS_RUANG = "kamus_ruang"
SUMBER_KAMUS_KATEGORI = "kamus_kategori"
SUMBER_KAMUS_PLUGIN = "kamus_plugin"     # kamus kategori Fitur Tambahan (H2, titik `nlp_kamus`)
SUMBER_NAMA_AMPLOP = "nama_amplop"


def kata_kamus(description: str) -> list:
    """Kata untuk kamus ruang: seperti `extract_keywords`, tanpa token nominal/angka dan tanpa kata > `KATA_MAKS`."""
    words = [w for w in extract_keywords(description) if " " not in w and w not in _SATUAN and not _NOMINAL.match(w)]
    out = list(dict.fromkeys(words))[:KATA_JUMLAH]
    phrase = " ".join(out)
    if phrase and phrase not in out:
        out.append(phrase)
    return [w for w in out if len(w) <= KATA_MAKS]


def guess_envelope_name(description):
    desc_lower = description.lower()
    for envelope_name, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                return envelope_name
    return None


async def save_learned_keywords(user_id, description: str, envelope_id, db, *, kamus_ruang: bool = False):
    """Belajar kata → amplop untuk user. `kamus_ruang=True` (hanya jalur web untuk catatan bukan-privat; R7): juga
    mengajari kamus ruang bila amplopnya amplop bersama di ruang usaha. Tidak meng-commit."""
    from app.models.models import UserEnvelopeKeyword
    from sqlalchemy import select as _sel
    keywords = extract_keywords(description)
    for kw in keywords:
        res = await db.execute(
            _sel(UserEnvelopeKeyword).where(
                UserEnvelopeKeyword.user_id == user_id,
                UserEnvelopeKeyword.keyword == kw,
                UserEnvelopeKeyword.envelope_id == envelope_id,
            )
        )
        existing = res.scalar_one_or_none()
        if existing:
            existing.count += 1
        else:
            db.add(UserEnvelopeKeyword(user_id=user_id, keyword=kw, envelope_id=envelope_id))
    if kamus_ruang:
        await ajari_kamus_ruang(db, user_id, description, envelope_id)


async def ajari_kamus_ruang(db, user_id, description: str, envelope_id) -> int:
    """Kamus ruang (R7): kata dari `description` → `envelope_id`, hanya bila amplop itu amplop bersama (tanpa
    `owner_id`), aktif, bertujuan pengeluaran, di ruang usaha. Upsert atomik (dua anggota mengajarkan kata yang sama
    bersamaan tidak saling menggagalkan). Kembali: jumlah kata yang diajarkan. Tidak meng-commit."""
    from datetime import datetime, timezone
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models.models import Envelope, Household, HouseholdType, RuangKamus
    row = (await db.execute(
        select(Envelope.household_id, Envelope.owner_id, Envelope.purpose, Envelope.is_active, Household.type)
        .join(Household, Household.id == Envelope.household_id).where(Envelope.id == envelope_id)
    )).first()
    if (row is None or row.owner_id is not None or not row.is_active
            or str(getattr(row.purpose, "value", row.purpose)) != "expense"
            or str(getattr(row.type, "value", row.type)) != HouseholdType.USAHA):
        return 0
    kata = kata_kamus(description)
    sekarang = datetime.now(timezone.utc)
    for kw in kata:
        await db.execute(
            pg_insert(RuangKamus)
            .values(id=uuid.uuid4(), household_id=row.household_id, keyword=kw, envelope_id=envelope_id, count=1,
                    diajarkan_oleh=user_id)
            .on_conflict_do_update(index_elements=["household_id", "keyword", "envelope_id"],
                                   set_={"count": RuangKamus.count + 1, "diajarkan_oleh": user_id,
                                         "updated_at": sekarang})
        )
    return len(kata)


@dataclass
class Tebakan:
    """Hasil `cari_amplop`. `sumber`: kata_saya | kamus_ruang | kamus_plugin | kamus_kategori | nama_amplop (None bila
    tidak ada); `kali` = jumlah kali kata itu diajarkan (kata_saya, kamus_ruang); `diajarkan_oleh` = user id pengajar terakhir
    di kamus ruang (route mengganti dengan nama)."""
    envelope: object = None
    confident: bool = False
    sumber: str | None = None
    kali: int | None = None
    diajarkan_oleh: uuid.UUID | None = None


async def find_best_envelope(description, household_id, db, user_id=None):
    t = await cari_amplop(description, household_id, db, user_id)
    return t.envelope, t.confident


async def _kamus_ruang(db, household_id, description, env_by_id) -> Tebakan | None:
    """Kamus ruang usaha `household_id` (R7). Dibaca hanya bila ruang itu bertipe usaha (gerbang di kueri, bukan
    hanya karena ruang keluarga tidak pernah ditulis). Skor = jumlah `count` per amplop yang boleh (`env_by_id`)."""
    from app.models.models import Household, HouseholdType, RuangKamus
    kata = kata_kamus(description)
    if not kata:
        return None
    rows = (await db.execute(
        select(RuangKamus.envelope_id, RuangKamus.count, RuangKamus.diajarkan_oleh)
        .join(Household, Household.id == RuangKamus.household_id)
        .where(RuangKamus.household_id == household_id, Household.type == HouseholdType.USAHA,
               RuangKamus.keyword.in_(kata))
    )).all()
    skor, pengajar = {}, {}
    for eid, count, oleh in rows:
        eid = str(eid)
        if eid not in env_by_id:
            continue
        skor[eid] = skor.get(eid, 0) + count
        if count >= pengajar.get(eid, (0, None))[0]:
            pengajar[eid] = (count, oleh)
    if not skor:
        return None
    best = max(skor, key=lambda x: skor[x])
    return Tebakan(env_by_id[best], True, SUMBER_KAMUS_RUANG, skor[best], pengajar[best][1])


async def cari_amplop(description, household_id, db, user_id=None, *, amplop_boleh=None) -> Tebakan:
    """Tebakan amplop untuk `description` di ruang `household_id`. `amplop_boleh` (karyawan, R7): hanya amplop di
    himpunan id ini yang menjadi kandidat, supaya amplop terkunci tidak menutupi tebakan berikutnya."""
    from sqlalchemy import or_
    from app.models.models import Envelope
    query = select(Envelope).where(
        Envelope.household_id == household_id, Envelope.is_active == True,
    )
    if user_id:
        # Amplop personal anggota lain tidak boleh jadi tujuan (kontrak
        # visibilitas household — sama dengan dropdown amplop di web).
        query = query.where(or_(Envelope.owner_id == None, Envelope.owner_id == user_id))
    result = await db.execute(query)
    envelopes = result.scalars().all()
    # Filter out saving/sinking_fund — NLP should only match expense envelopes
    envelopes = [e for e in envelopes if str(getattr(e, "purpose", "expense")) == "expense"]
    if amplop_boleh is not None:
        boleh = {str(a) for a in amplop_boleh}
        envelopes = [e for e in envelopes if str(e.id) in boleh]
    if not envelopes:
        return Tebakan()

    env_by_id = {str(e.id): e for e in envelopes}

    # 0. Learned keywords — highest score wins
    if user_id:
        from app.models.models import UserEnvelopeKeyword
        keywords = extract_keywords(description)
        if keywords:
            scores = {}
            for kw in keywords:
                kw_res = await db.execute(
                    select(UserEnvelopeKeyword).where(
                        UserEnvelopeKeyword.user_id == user_id,
                        UserEnvelopeKeyword.keyword == kw,
                    )
                )
                for row in kw_res.scalars().all():
                    eid = str(row.envelope_id)
                    if eid in env_by_id:
                        scores[eid] = scores.get(eid, 0) + row.count
            if scores:
                best_id = max(scores, key=lambda x: scores[x])
                return Tebakan(env_by_id[best_id], True, SUMBER_KATA_SAYA, scores[best_id])

    # 0b. Kamus ruang usaha (R7): sesudah kata user sendiri, sebelum kamus kategori.
    if household_id:
        t = await _kamus_ruang(db, household_id, description, env_by_id)
        if t is not None:
            return t

    # Plugin H2 (titik `nlp_kamus`): kamus kategori Fitur Tambahan yang aktif di ruang ini, dicoba sebelum kamus
    # kategori inti (05-desain-buku-usaha.md B: kata user → kamus ruang → kamus kategori). Tanpa plugin berkamus:
    # tanpa kueri. Kamus plugin tidak pernah dipakai di ruang yang tidak memasangnya.
    guessed_name = None
    if user_id:
        from app.plugins.host import titik
        if titik.ada_kamus():
            guessed_name = titik.tebak_kamus(await titik.kamus_ruang(db, household_id, user_id), description)
    sumber_kategori = SUMBER_KAMUS_PLUGIN if guessed_name else SUMBER_KAMUS_KATEGORI
    guessed_name = guessed_name or guess_envelope_name(description)

    # 1. Exact match on guessed category name
    if guessed_name:
        for env in envelopes:
            if env.name.lower() == guessed_name.lower():
                return Tebakan(env, True, sumber_kategori)

    # 2. Partial match — confident=False because partial matches are ambiguous
    if guessed_name:
        g = guessed_name.lower()
        for env in envelopes:
            e = env.name.lower()
            if g in e or e in g:
                return Tebakan(env, False, sumber_kategori)

    # 3. Envelope name appears directly in description
    desc_lower = description.lower()
    for env in envelopes:
        if env.name.lower() in desc_lower:
            return Tebakan(env, True, SUMBER_NAMA_AMPLOP)

    return Tebakan()
