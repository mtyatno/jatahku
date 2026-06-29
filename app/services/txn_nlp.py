"""Shared transaction NLP: keyword extraction, category guessing, per-user
learned keyword matching. Used by both the Telegram bot and the web API so the
two channels share one classification + learning implementation."""
from sqlalchemy import select

STOPWORDS = {"di", "ke", "dari", "yang", "dan", "untuk", "dengan", "ya", "aku",
             "saya", "kamu", "ini", "itu", "ada", "buat", "sama", "juga", "mau",
             "beli", "bayar", "beli", "tadi", "lagi", "udah", "sudah", "pas", "aja"}

CATEGORY_KEYWORDS = {
    "makan": ["makan", "nasi", "ayam", "sate", "bakso", "mie", "noodle", "rice",
              "lunch", "dinner", "breakfast", "sarapan", "siang", "malam",
              "warteg", "padang", "resto", "restaurant", "cafe", "kafe",
              "kopi", "coffee", "starbucks", "mcd", "kfc", "pizza",
              "gofood", "grabfood", "shopeefood", "snack", "jajan"],
    "transport": ["grab", "gojek", "ojek", "taxi", "bensin", "parkir",
                  "tol", "busway", "mrt", "krl", "kereta", "bus",
                  "transport", "uber", "maxim", "indriver"],
    "hiburan": ["nonton", "film", "bioskop", "game", "steam", "netflix",
                "spotify", "youtube", "premium", "langganan", "subscribe",
                "hangout", "karaoke", "mall"],
    "belanja": ["baju", "pakaian", "fashion", "kaos", "celana", "jaket", "kemeja", "dress",
                "sepatu", "sandal", "tas", "dompet", "aksesoris", "jam tangan",
                "shopee", "tokped", "tokopedia", "lazada", "tiktok shop", "belanja", "online", "shop"],
    "tagihan": ["listrik", "air", "pdam", "internet", "wifi", "pulsa",
                "token", "indihome", "telkom", "pln"],
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


def guess_envelope_name(description):
    desc_lower = description.lower()
    for envelope_name, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                return envelope_name
    return None


async def save_learned_keywords(user_id, description: str, envelope_id, db):
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


async def find_best_envelope(description, household_id, db, user_id=None):
    from app.models.models import Envelope
    result = await db.execute(
        select(Envelope).where(
            Envelope.household_id == household_id, Envelope.is_active == True,
        )
    )
    envelopes = result.scalars().all()
    if not envelopes:
        return None, False

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
                return env_by_id[best_id], True

    guessed_name = guess_envelope_name(description)

    # 1. Exact match on guessed category name
    if guessed_name:
        for env in envelopes:
            if env.name.lower() == guessed_name.lower():
                return env, True

    # 2. Partial match — confident=False because partial matches are ambiguous
    if guessed_name:
        g = guessed_name.lower()
        for env in envelopes:
            e = env.name.lower()
            if g in e or e in g:
                return env, False

    # 3. Envelope name appears directly in description
    desc_lower = description.lower()
    for env in envelopes:
        if env.name.lower() in desc_lower:
            return env, True

    return None, False
