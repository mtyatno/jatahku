"""Profil aplikasi (bank, e-wallet) untuk pembaca QRIS dan transfer. Data, bukan kode:
kata pengenal aplikasi (penerbit) dan sinonim label per field. Menambah aplikasi biasanya
cukup menambah satu entri di PROFILES; label dan tata letak khusus aplikasi diisi dari korpus nyata (Task A14)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from app.services.kotak_struk.config import LAYOUT_LABEL_MAX
from app.services.kotak_struk.readers.labels import count_markers, learned_amount, learned_datetime, mask_partial_labels


@dataclass
class AppProfile:
    key: str                                    # disimpan di Dokumen Bayar sebagai `issuer`
    label: str                                  # nama untuk manusia
    markers: list[str]                          # kata pengenal aplikasi di bukti
    labels: dict[str, list[str]] = field(default_factory=dict)   # sinonim label khusus aplikasi, per field
    # Tata letak: pihak lawan dicetak tanpa label sebagai baris pertama di bawah logo, sebelum nominal (nama, lalu kota
    # untuk QRIS atau "Bank/e-wallet · nomor" untuk transfer); lihat proof_common.read_header_party.
    party_on_top: bool = False
    # Kalimat yang aplikasi ini cetak pada bukti transaksi yang selesai. Hanya dipakai bila tidak ada kata status sama
    # sekali (gagal/pending selalu menang; lihat proof_common.read_status).
    done_phrases: list[str] = field(default_factory=list)


# Sinonim label per field; urutan = prioritas. Daftar rencana tetap ada (dalam urutan yang sama);
# varian dekat ("Nama Penerima", "Nomor Rekening", "Nomor Referensi", ...) ditambahkan di antaranya.
# Kunci di luar rencana: `sender`, `status` (pembaca transfer), `discount`, `tax`, `extra` (cek silang nominal).
GENERIC_LABELS: dict[str, list[str]] = {
    "amount": ["nominal", "jumlah", "jumlah pembayaran", "total bayar", "total pembayaran", "total", "amount"],
    "fee": ["biaya admin", "biaya", "admin", "fee"],
    # Tambahan di atas nominal yang ikut masuk total seperti biaya. Terpisah dari `fee` karena kata awalnya juga kata biasa
    # ("TIP TOP SWALAYAN", "DONASI KITA BERSAMA"): baris berawalan ini tidak dianggap baris label saat nilai label lain hilang.
    "extra": ["tips", "tip", "service fee", "service charge", "layanan", "ongkir", "donasi"],
    "discount": ["diskon", "potongan", "promo", "voucher", "discount"],
    "tax": ["pajak", "ppn", "pb1", "tax"],
    # "merchant name" lebih dulu: label "merchant" juga cocok dengan "Merchant Name"/"Merchant Location" (GoPay, A14 r2).
    "merchant": ["merchant name", "merchant", "nama merchant", "nama penerima", "penerima", "nama tujuan", "tujuan", "ke",
                 "ditransfer ke", "dikirim ke"],
    "city": ["lokasi", "kota", "merchant location", "lokasi merchant"],
    "ref": ["no. referensi", "no referensi", "nomor referensi", "referensi", "no. ref", "no ref", "ref", "rrn", "reference no",
            "id transaksi", "no. transaksi", "no transaksi", "nomor transaksi", "transaction id"],
    "nmid": ["nmid"],
    "account": ["rekening tujuan", "nomor rekening tujuan", "no. rekening tujuan", "no rekening tujuan", "rekening penerima",
                "no. rekening", "no rekening", "nomor rekening", "rekening"],
    "bank": ["bank tujuan", "bank penerima", "bank"],
    "note": ["berita transfer", "berita", "keterangan", "catatan"],
    "sender": ["nama pengirim", "pengirim", "dari", "dikirim dari"],
    "status": ["status transaksi", "status"],
    # Rekening/akun user sendiri. Tidak dibaca sebagai field; barisnya label (bukan nama, barang, atau nilai label lain).
    "source": ["sumber akun", "sumber dana", "rekening sumber", "sumber rekening", "rekening asal"],
    # Jam di baris berlabel sendiri, terpisah dari tanggal ("Waktu 9:31" + "Tanggal 31 Okt 2026", GoPay).
    "time": ["waktu", "jam", "pukul", "time"],
}

PROFILES: list[AppProfile] = [
    AppProfile("bca_mobile", "BCA mobile", ["bca", "m-bca", "mybca"]),
    AppProfile("livin", "Livin' by Mandiri", ["livin", "mandiri"]),
    AppProfile("brimo", "BRImo", ["brimo", "bri"]),
    AppProfile("bni", "BNI Mobile (wondr)", ["wondr", "bni"]),
    AppProfile("bsi", "BSI Mobile", ["bsi", "byond"]),
    # Dikalibrasi A14 ronde 1 (5 bukti asli Jago Syariah: QRIS, transfer ke e-wallet dan bank, PLN, pulsa).
    AppProfile("jago", "Bank Jago", ["jago"], labels={"ref": ["id transaksi", "nomor referensi"]}, party_on_top=True,
               done_phrases=["resi ini merupakan bukti transaksi yang sah"]),
    AppProfile("seabank", "SeaBank", ["seabank"]),
    AppProfile("blu", "blu by BCA Digital", ["blu"]),
    AppProfile("gopay", "GoPay", ["gopay"]),
    AppProfile("ovo", "OVO", ["ovo"]),
    AppProfile("dana", "DANA", ["dana"]),
    # Dikalibrasi A14 ronde 3 (3 bukti asli: QRIS, kirim ke GoPay, kirim ke rekening bank).
    # "Kirim Ke" hanya label penerima di ShopeePay: di tempat lain kata biasa ("Kirim ke alamat pembeli" di struk toko).
    AppProfile("shopeepay", "ShopeePay", ["shopeepay"],
               labels={"merchant": ["kirim ke"], "ref": ["transaksi sn", "order sn"]}),
]

# Bank dan e-wallet yang bisa jadi tujuan transfer (selain penanda di PROFILES). Data: baris "GoPay · 0812…" atau
# "Mandiri · 123…" di bawah nama penerima berarti transfer; "PLN Prepaid · 5500…" atau "Indosat · 0815…" tagihan/pulsa.
MONEY_PROVIDERS = [
    "bank", "bca", "mandiri", "bri", "bni", "bsi", "btn", "cimb", "niaga", "permata", "danamon", "mega", "ocbc", "maybank",
    "panin", "btpn", "jenius", "uob", "hsbc", "sinarmas", "bjb", "bpd", "nagari", "muamalat", "neo", "allo", "superbank",
    "krom", "linkaja", "isaku", "sakuku", "flip",
]


# Kata yang boleh menyertai nama aplikasi di baris logo ("Jago Syariah", "livin' by mandiri", "BCA mobile", "Bank Jago").
LOGO_WORDS = {"syariah", "by", "mobile", "bank", "digital", "app", "banking"}


def logo_profile(line: str) -> AppProfile | None:
    """Profil aplikasi bila baris ini baris logo: hanya nama aplikasi (penanda profil) dan kata pendamping LOGO_WORDS.
    Nama usaha yang memuat kata bank/aplikasi ("TOKO MANDIRI JAYA", "KANTIN BNI", "JAGO COFFEE") bukan logo."""
    words = [w.strip("'") for w in re.findall(r"[a-z0-9][a-z0-9'.-]*", (line or "").lower())]
    words = [w for w in words if w]
    markers = {m for p in PROFILES for m in p.markers}
    if not words or not any(w in markers for w in words) or any(w not in markers | LOGO_WORDS for w in words):
        return None
    best = _best_profiles([line])
    return best[0] if best else None


def is_money_provider(name: str | None) -> bool:
    """Nama penyedia ("GoPay", "Mandiri", "Bank Jago Syariah") adalah bank atau e-wallet."""
    words = set(re.findall(r"[a-z][a-z'-]*", (name or "").lower()))
    known = {w for p in PROFILES for w in p.markers} | set(MONEY_PROVIDERS)
    return bool(words & known)


def is_provider_only(name: str | None) -> bool:
    """Teks hanya nama bank/e-wallet (dan kata pendamping logo): "Bank Jago Syariah", "GoPay", "BANK BCA". Nama yang
    sekadar memuat nama aplikasi ("GOPAY TOPU-SXXXX", "Shopeepaysitxx Amixxxxx") bukan."""
    words = re.findall(r"[a-z][a-z'-]*", (name or "").lower())
    known = {w for p in PROFILES for w in p.markers} | set(MONEY_PROVIDERS)
    return bool(words) and is_money_provider(name) and all(w in known | LOGO_WORDS for w in words)


# Baris "Penyedia · nomor" di bawah nama pihak lawan ("Mandiri·…4321", "Bank Jago Syariah•", "GoPay · 0812…"): bank
# di sana milik pihak lawan, bukan aplikasi yang dipakai user. Diawali huruf (baris tanggal "29 Okt 2026·19:35" tidak).
PROVIDER_LINE = re.compile(r"^\s*(?P<name>[A-Za-z][A-Za-z0-9'&.\- ]*?)\s*[·•]\s*(?P<rest>.*?)\s*$")

# Kata "dana" juga kata biasa ("Dana Masuk", "Terima Dana"); bukan penanda aplikasi DANA.
_COMMON_PHRASES = re.compile(
    r"(?<!\w)(dana\s+(masuk|keluar|tersedia|anda|diterima)|(terima|menerima|sumber)\s+dana)(?!\w)", re.IGNORECASE)
# Baris tentang pihak lawan (bank/rekening tujuan, penerima, pengirim): bank atau nama di sana
# bukan aplikasi yang dipakai user ("Bank Tujuan BCA" tidak berarti bukti ini dari BCA mobile).
_COUNTERPARTY_LABELS = ["bank tujuan", "bank penerima", "rekening tujuan", "rekening penerima", "nama merchant", "merchant name",
                        "merchant", "nama penerima", "penerima", "nama tujuan", "tujuan", "ke", "ditransfer ke", "dikirim ke",
                        "kirim ke", "nama pengirim", "pengirim", "dari", "dikirim dari"]
# Baris bank/e-wallet + nomor milik pihak lawan, tepat di bawah nama berlabel ("Ditransfer ke BUDI" lalu "Mandiri 1234…",
# "ShopeePay …6390", "Tabungan by Jago …8136"; GoPay; "GoPay: 0812…", ShopeePay).
PARTY_ACCOUNT_LINE = re.compile(r"^\s*(?P<name>[A-Za-z][A-Za-z0-9'&.\- ]*?)\s*[·•\-:]?\s*(?P<number>[\d*•…][\d *•…\-]*\d)\s*$")
_COUNTERPARTY_LINE = re.compile(
    r"^\s*(?:" + "|".join(r"\s+".join(re.escape(part) for part in label.split()) for label in _COUNTERPARTY_LABELS)
    + r")(?=$|[\s:：])(.*)$", re.IGNORECASE)


def _issuer_lines(lines: list[str]) -> list[str]:
    """Baris yang boleh jadi petunjuk penerbit: tanpa baris pihak lawan (dan nilainya di baris
    bawah bila labelnya berdiri sendiri) dan tanpa frasa "dana" biasa."""
    out, skip_next = [], False
    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue
        m = _COUNTERPARTY_LINE.match(line)
        if m:
            # nilai di baris bawah, atau baris bank/rekening pihak lawan di bawah nama sebaris
            skip_next = not m.group(1).strip() or bool(i + 1 < len(lines) and PARTY_ACCOUNT_LINE.match(lines[i + 1])
                                                       and not _COUNTERPARTY_LINE.match(lines[i + 1]))
            continue
        if PROVIDER_LINE.match(line):
            continue
        out.append(_COMMON_PHRASES.sub(" ", line))
    return out


def _best_profiles(lines: list[str]) -> list[AppProfile]:
    """Profil-profil dengan penanda terbanyak (urutan PROFILES); kosong bila tidak ada penanda."""
    usable = _issuer_lines(lines)
    counts = [(profile, count_markers(usable, profile.markers)) for profile in PROFILES]
    best = max(count for _, count in counts)
    return [profile for profile, count in counts if count == best] if best else []


def detect_issuer(lines: list[str]) -> AppProfile | None:
    """Profil dengan penanda terbanyak. Seri dimenangkan profil baris logo di baris pertama (`logo_profile`) bila baris kedua
    bukan logo aplikasi lain yang juga seri: nama aplikasi lain di badan bukti ("Nama Pengakuisisi Gopay", penerima "GOPAY
    TOPU-…" di bukti ShopeePay) bukan aplikasi yang dipakai user. Selain itu yang lebih dulu di PROFILES (["BRImo", "BCA"])."""
    best = _best_profiles(lines)
    if len(best) > 1:
        logos = [p for line in lines[:2] if (p := logo_profile(line)) in best]
        if logos and logos[0] is logo_profile(lines[0]) and all(p is logos[0] for p in logos):
            return logos[0]
    return best[0] if best else None


def labels_for(profile: AppProfile | None, field: str) -> list[str]:
    """Sinonim label untuk `field`: label profil dulu, lalu generik (tanpa duplikat). Pada profil dari `with_learned`
    label aturan belajar yang disetujui ada di depan label profil, jadi didahulukan; label profil dan generik tetap
    dipakai bila label aturan tidak menemukan nilai. Field `paid_at` hanya ada di profil seperti itu (GENERIC kosong)."""
    own = profile.labels.get(field, []) if profile else []
    seen: set[str] = set()
    out = []
    for label in [*own, *GENERIC_LABELS.get(field, [])]:
        if label.lower() not in seen:
            seen.add(label.lower())
            out.append(label)
    return out


# ── Aturan belajar yang disetujui (spec 2026-11-01 §5; plan Task L3) ─────────

RULE_TOTAL, RULE_PARTY, RULE_DATE = "label_total", "label_pihak", "label_tanggal"


@dataclass(frozen=True)
class Learned:
    """Label dari aturan belajar yang disetujui untuk satu kunci aplikasi, urut prioritas (pendukung terbanyak dulu):
    `total` (`label_total`), `party` (`label_pihak`, label penerima), `date` (`label_tanggal`). Kosong = tanpa aturan."""
    total: list[str] = field(default_factory=list)
    party: list[str] = field(default_factory=list)
    date: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.total or self.party or self.date)


def _rule_labels(values) -> list[str]:
    """Label aturan yang dipakai pembaca: teks, huruf kecil, spasi dirapatkan, tidak kosong, <= LAYOUT_LABEL_MAX karakter
    (bentuk nilai `proof_rules`: `kerangka.safe_label`), tanpa duplikat, urutan tetap. Selain itu dilewati."""
    if not isinstance(values, (list, tuple)):
        return []
    out: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        label = " ".join(value.lower().split())
        if label and len(label) <= LAYOUT_LABEL_MAX and label not in out:
            out.append(label)
    return out


def learned_for(rules: dict | None, key: str | None) -> Learned:
    """Label aturan untuk kunci aturan `key` (`kerangka.rule_key`) dari `ParseContext.rules`; `Learned()` bila tanpa
    aturan, tanpa kunci, atau bentuknya rusak. Aturan kunci lain tidak pernah dibaca."""
    if not key or not isinstance(rules, dict):
        return Learned()
    found = rules.get(key)
    if not isinstance(found, dict):
        return Learned()
    return Learned(total=_rule_labels(found.get(RULE_TOTAL)), party=_rule_labels(found.get(RULE_PARTY)),
                   date=_rule_labels(found.get(RULE_DATE)))


def with_learned(profile: AppProfile | None, learned: Learned) -> AppProfile | None:
    """Profil untuk membaca label dengan aturan belajar: `profile` apa adanya bila `learned` kosong. Selain itu salinan
    (profil None -> profil kosong tanpa penanda) dengan label penerima aturan di depan `labels["merchant"]` dan label
    tanggal aturan di `labels["paid_at"]`. Label pengirim (`sender`) tidak diubah: aturan `label_pihak` hanya label
    PENERIMA (belajar._party_label), dan label penerima sebagai label pengirim akan membaca user sebagai pengirim. Label
    total tidak masuk `labels["amount"]` (di sana label selain "total*" = subtotal; K6): pembaca membacanya sendiri
    (`labels.learned_amount`). `doc.issuer`, status, dan penanda tetap dari profil asli."""
    if not learned:
        return profile
    base = profile if profile is not None else AppProfile(key="", label="", markers=[])
    labels = dict(base.labels)
    if learned.party:
        labels["merchant"] = [*learned.party, *labels.get("merchant", [])]
    if learned.date:
        labels["paid_at"] = list(learned.date)
    return replace(base, labels=labels)


def learned_profile(lines: list[str], profile: AppProfile | None, rules: dict | None) -> tuple[Learned, AppProfile | None]:
    """(label aturan, profil berlabel aturan) untuk satu bukti: kunci aturan dari `kerangka.rule_key` (tahap 1: kunci
    profil), lalu `learned_for` dan `with_learned`. Tanpa aturan: `(Learned(), profile)` tanpa menghitung kunci apa pun.
    Pembaca hanya memakai label aturannya: total (`learned_total`), tanggal (`learned_paid_at`), dan nama penerima
    (`learned_party`); nilai lain dan status dibaca dengan profil asli (review L3 I-1)."""
    if not rules:
        return Learned(), profile
    # Impor di sini: kerangka mengimpor modul pembaca (impor melingkar bila di tingkat modul).
    from app.services.kotak_struk.kerangka import rule_key
    learned = learned_for(rules, rule_key(lines, profile, forbidden_words=set()))
    return learned, with_learned(profile, learned)


def learned_total(amounts, confidence: str | None, body: list[str], labels: list[str]):
    """(nominal, keyakinan total) sesudah label aturan `label_total` (K6), yang dibaca LEBIH DULU dari label biasa: bila
    labelnya menemukan nominal (`labels.learned_amount`), itu total dengan keyakinan `tinggi`; subtotal, biaya, pajak,
    dan diskon tetap hasil baca biasa, jadi cek `selisih_nominal` tetap jalan. Selain itu `amounts`/`confidence` apa
    adanya (objek yang sama)."""
    total = learned_amount(body, labels)
    if total is None:
        return amounts, confidence
    return replace(amounts, total=total), "tinggi"


def learned_paid_at(body: list[str], labels: list[str]):
    """(waktu bayar, "tinggi") dari label aturan `label_tanggal` (keyakinan aturan yang disetujui = tinggi, spec §5), atau
    None: pembaca memakai `proof_common.read_paid_at` seperti biasa."""
    paid_at = learned_datetime(body, labels)
    return (paid_at, "tinggi") if paid_at is not None else None


def learned_party(body: list[str], profile: AppProfile | None, labels: list[str]):
    """(baris, profil) untuk membaca pihak lawan dengan label penerima aturan (`label_pihak`), atau None bila tidak ada
    label aturan yang cocok PERSIS dengan satu baris (review L3 m-2: "tujuan" tidak membaca "Tujuan Transfer Lainnya").
    Baris yang hanya diawali label aturan dikosongkan (`labels.mask_partial_labels`); profilnya hanya membawa label
    penerima aturan (tanpa label tanggal), di depan label penerima profil."""
    if not labels:
        return None
    # Impor di sini: kerangka mengimpor modul pembaca (impor melingkar bila di tingkat modul).
    from app.services.kotak_struk.kerangka import LABEL_WORDS
    masked, whole = mask_partial_labels(body, labels, LABEL_WORDS)
    if not whole:
        return None
    return masked, with_learned(profile, Learned(party=list(labels)))
