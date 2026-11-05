"""Penyamaran baris teks bukti bayar (Kotak Struk): nomor dan nama.

Modul murni (tanpa database, tanpa variabel lingkungan, tanpa pembaca), dipakai dua tempat:
- `app/scripts/kotak_corpus.py` (`add`): menyamarkan baris sampel korpus. `mask_line`, `needs_review`, dan
  `MIN_RUN_DIGITS` dipindah dari sana tanpa perubahan (pre-flight A16 K2) dan diekspor ulang di sana.
- `donasi.sample_lines` di worker (donasi contoh tahap 2): baris tersamar dari user yang setuju.

`pseudonymise` mengganti setiap kata nama yang dikenal (pihak lawan, pengirim, merchant terbaca, user) dengan kata nama
samaran perannya (`PSEUDONYMS`, pre-flight A16 K5); nama lain yang tidak dikenali pembaca disamarkan pemilik di Admin.
"""
from __future__ import annotations

import re

# ── Nomor ───────────────────────────────────────────────────────────────────

MIN_RUN_DIGITS = 6

_MONTH_WORDS = {
    "januari", "january", "jan", "februari", "february", "feb", "peb", "maret", "march", "mar", "april", "apr",
    "mei", "may", "juni", "june", "jun", "juli", "july", "jul", "agustus", "august", "agu", "ags", "aug",
    "september", "sept", "sep", "oktober", "october", "okt", "oct", "november", "nopember", "nov", "nop",
    "desember", "december", "des", "dec",
}

_HWS = r"[^\S\r\n]"                    # spasi horizontal jenis apa pun: spasi, NBSP, U+202F, U+2009, tab, ...
_DASH = "\\-\u2010-\u2015\u2212"       # isi kelas karakter: "-", U+2010..U+2015, U+2212 (minus)
# Pemisah di dalam satu deret digit: <= 2 spasi (OCR menyambung kotak dengan dua spasi), satu strip jenis apa pun
# (boleh diapit satu spasi), atau satu titik/koma.
_RUN_SEP = rf"(?:{_HWS}{{1,2}}|{_HWS}?[{_DASH}]{_HWS}?|[.,])"
_DIGIT_RUN = re.compile(rf"\d+(?:{_RUN_SEP}\d+)*")

# Nominal berkelompok ribuan yang ketat: kelompok pertama 1-3 digit dan tidak berawalan 0, sisanya tepat 3, pemisah
# konsisten, desimal 2 digit opsional dengan pemisah yang lain (1.500.000 / 150,000.00 / 1.500.000,00).
# "081.234.567.890" dan "0.123.456.789" bukan nominal.
_THOUSANDS = r"(?!0)\d{1,3}(?P<g>[.,])\d{3}(?:(?P=g)\d{3})*(?:(?!(?P=g))[.,]\d{2})?"
_NUM_END = rf"(?![.,]?\d)(?![{_DASH}]\d)"   # tidak bersambung ke digit lain
_NMID_LINE = re.compile(r"nmid", re.IGNORECASE)
# NMID QRIS (publik): "ID" + >= 10 digit, hanya di baris berlabel NMID.
_NMID = re.compile(rf"(?<![A-Za-z0-9])ID{_HWS}?\d{{10,}}", re.IGNORECASE)
# Nominal langsung sesudah Rp/IDR: nominal ribuan ketat, atau angka tanpa kelompok <= 9 digit (Rp 999.999.999) yang
# tidak berawalan 0 + digit ("Rp 0" dan "Rp 0,00" tetap nominal; "Rp 081234567" bukan).
_CURRENCY = re.compile(
    rf"(?<![A-Za-z])(?:rp|idr){_HWS}*[.:]?{_HWS}*(?:{_THOUSANDS}|(?!0\d)\d{{1,9}}(?:[.,]\d{{2}})?){_NUM_END}",
    re.IGNORECASE)
# Tanggal angka dengan pemisah yang sama: d-m-y, d/m/y, d.m.y (tahun 2 atau 4 digit) dan y-m-d. Tidak boleh
# menempel pada deret angka lain ("1234-12-10-26" bukan tanggal, melainkan nomor yang harus disamarkan).
_DATE_DMY = re.compile(rf"(?<!\d)(?<!\d[/.{_DASH}])(\d{{1,2}})([-/.])(\d{{1,2}})\2(\d{{4}}|\d{{2}})(?![/.{_DASH}]?\d)")
_DATE_YMD = re.compile(rf"(?<!\d)(?<!\d[/.{_DASH}])(\d{{4}})([-/.])(\d{{1,2}})\2(\d{{1,2}})(?![/.{_DASH}]?\d)")
# Tanggal dengan nama bulan di depan ("Oct 26 2026", "Okt 26, 2026"): hari dan tahun hanya dipisah spasi.
_DATE_MDY = re.compile(r"(?<![A-Za-z])([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)")
# Tanggal dengan nama bulan di tengah ("26 Okt 2026", "26-Okt-2026", "26Okt2026"; pemisah seperti labels._DMY_NAME
# pembaca). Hari dan tahunnya tidak membentuk satu deret, jadi mask_line tidak mengubahnya; sebagai rentang yang
# dibiarkan, 6 digitnya tidak dihitung PERIKSA dan deret di sampingnya tidak menyeret harinya.
_NAME_DATE_SEP = rf"(?:{_HWS}|[.,/-])*"
_DATE_DMY_NAME = re.compile(
    rf"(?<!\d)(?<!\d[/.{_DASH}])(\d{{1,2}})(?:st|nd|rd|th)?{_NAME_DATE_SEP}([A-Za-z]{{3,9}}){_NAME_DATE_SEP}(\d{{4}})"
    rf"(?![/.{_DASH}]?\d)")
# Jam: 08:12, 08:12:33, 08.12.33.
_TIME = re.compile(r"(?<![\d:.])(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?(?!\d|[:.]\d)")
# Nominal ribuan ketat tanpa Rp. Tidak boleh menempel strip pada deret lain ("01.234.567.8-901.000").
_GROUPED = re.compile(rf"(?<![\d.,])(?<!\d[{_DASH}]){_THOUSANDS}{_NUM_END}")


def _year_ok(year: str) -> bool:
    return len(year) == 2 or 1900 <= int(year) <= 2099


def _dmy_ok(m: re.Match) -> bool:
    return 1 <= int(m.group(1)) <= 31 and 1 <= int(m.group(3)) <= 12 and _year_ok(m.group(4))


def _ymd_ok(m: re.Match) -> bool:
    return _year_ok(m.group(1)) and 1 <= int(m.group(3)) <= 12 and 1 <= int(m.group(4)) <= 31


def _mdy_ok(m: re.Match) -> bool:
    return m.group(1).lower() in _MONTH_WORDS and 1 <= int(m.group(2)) <= 31 and _year_ok(m.group(3))


def _dmy_name_ok(m: re.Match) -> bool:
    return 1 <= int(m.group(1)) <= 31 and m.group(2).lower() in _MONTH_WORDS and _year_ok(m.group(3))


def _time_ok(m: re.Match) -> bool:
    return int(m.group(1)) <= 23 and int(m.group(2)) <= 59 and int(m.group(3) or 0) <= 59


# Urutan = prioritas: rentang yang ditemukan lebih dulu menang bila bertumpang tindih.
_KEEP = (
    (_CURRENCY, None), (_DATE_DMY, _dmy_ok), (_DATE_YMD, _ymd_ok), (_DATE_MDY, _mdy_ok),
    (_DATE_DMY_NAME, _dmy_name_ok), (_TIME, _time_ok), (_GROUPED, None),
)


def _kept_spans(line: str) -> list[tuple[int, int]]:
    rules = (((_NMID, None),) if _NMID_LINE.search(line) else ()) + _KEEP
    spans: list[tuple[int, int]] = []
    for rx, valid in rules:
        for m in rx.finditer(line):
            if valid is not None and not valid(m):
                continue
            start, end = m.span()
            if all(end <= s or start >= e for s, e in spans):
                spans.append((start, end))
    return sorted(spans)


def _mask_runs(text: str) -> str:
    def repl(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group())
        return "…" + digits[-4:] if len(digits) >= MIN_RUN_DIGITS else m.group()
    return _DIGIT_RUN.sub(repl, text)


def mask_line(line: str) -> str:
    """Samarkan nomor rekening, nomor referensi, nomor HP, dan deret angka panjang lain di satu baris.

    Deret >= 6 digit (kelompoknya boleh dipisah <= 2 spasi jenis apa pun, satu strip jenis apa pun, atau satu
    titik/koma) menjadi `…` + 4 digit terakhirnya. Dibiarkan: nominal ribuan yang ketat (1.500.000, 150,000.00),
    nominal langsung sesudah Rp/IDR (ribuan ketat atau <= 9 digit), tanggal (d-m-y, d/m/y, d.m.y, y-m-d,
    "Oct 26 2026", "26 Okt 2026"), jam, dan NMID (`ID` + >= 10 digit) di baris berlabel NMID. Teks yang sudah
    tersamar (`…4567`, `****1234`) tidak berubah."""
    out, pos = [], 0
    for start, end in _kept_spans(line):
        out.append(_mask_runs(line[pos:start]))
        out.append(line[start:end])
        pos = end
    out.append(_mask_runs(line[pos:]))
    return "".join(out)


# Huruf yang sering dibaca OCR dari angka (0 1 5 8 2 6 9), dalam deret 1-3 huruf yang tidak menempel huruf lain:
# "S6", "BB", "lO" — bukan bagian kata ("SOSIS", "TID…", "WIB").
_LOOKALIKE_RUN = re.compile(r"(?<![^\W\d_])[OoDlIiSsBZGgq]{1,3}(?![^\W\d_])")
# Tepat satu karakter ini masih menyambung jam / nominal ke potongan nomor di sebelahnya: "/", "_", ":", ".", ",",
# dan semua strip yang mask_line anggap pemisah deret (_DASH).
_GLUE = re.compile(rf"[/_:.,{_DASH}]")
_HWS_RX = re.compile(_HWS)


def _is_time(text: str) -> bool:
    """Berbentuk jam yang sah (08:12, 08.12.33, juga "12.10.26" yang bisa tanggal d.m.yy); "24.12.34" hanya tanggal."""
    m = _TIME.fullmatch(text)
    return bool(m and _time_ok(m))


def _skip_spaces(blank: str, i: int, step: int, spaces: int) -> int:
    """Indeks sesudah melewati <= `spaces` spasi horizontal dari blank[i] ke arah `step`."""
    while spaces and 0 <= i < len(blank) and _HWS_RX.fullmatch(blank[i]):
        i, spaces = i + step, spaces - 1
    return i


def _number_at(blank: str, i: int, step: int, lookalike: set[int], spaces: int = 0) -> bool:
    """Apakah ke arah `step` dari blank[i] — langsung, atau lewat tepat satu pemisah `_GLUE`, masing-masing boleh
    didahului <= `spaces` spasi — ada digit, awal penanda `…dddd`, atau huruf mirip angka lepas. `blank` sudah
    mengosongkan rentang yang dibiarkan, jadi tetangga yang bagian dari tanggal/nominal/jam lain tidak terlihat."""
    i = _skip_spaces(blank, i, step, spaces)
    if 0 <= i < len(blank) and _GLUE.fullmatch(blank[i]):
        i = _skip_spaces(blank, i + step, step, spaces)
    return 0 <= i < len(blank) and (blank[i].isdecimal() or blank[i] == "…" or i in lookalike)


def _is_number_fragment(line: str, blank: str, start: int, end: int, lookalike: set[int]) -> bool:
    """Rentang yang dibiarkan line[start:end] berbentuk jam atau nominal ribuan tanpa Rp/IDR, dan menempel potongan
    nomor: jam langsung atau lewat satu pemisah ("…4903/09:45", "S6:25"); nominal tanpa Rp juga lewat 1-2 spasi di
    sekitar pemisah itu — celah antarkelompok sebuah nomor yang satu celahnya terbaca OCR sebagai titik/koma
    ("703.123 …6700", "182.222 8783", "…5678 - 901.000"). Nominal langsung sesudah Rp/IDR tetap nominal."""
    piece = line[start:end]
    if _is_time(piece):
        spaces = 0
    elif _GROUPED.fullmatch(piece):
        spaces = 2
    else:
        return False
    return _number_at(blank, start - 1, -1, lookalike, spaces) or _number_at(blank, end, 1, lookalike, spaces)


def needs_review(line: str) -> bool:
    """Jaring pengaman untuk tinjauan manusia (tidak pernah memblokir): hitungan seluruh baris sesudah `mask_line`.

    Rentang yang dibiarkan (nominal, tanggal, jam, NMID) dikosongkan — kecuali yang berupa potongan nomor
    (`_is_number_fragment`): jam yang menempel digit, penanda `…dddd`, atau huruf mirip angka lepas, langsung atau
    lewat satu pemisah `_GLUE`, dan nominal ribuan tanpa Rp/IDR yang menempel begitu atau lewat 1-2 spasi (juga di
    kedua sisi pemisah itu, re-review A13 I1-r4); digitnya tetap dihitung. Lalu dihitung: tiap digit 1 (penanda `…dddd` = 4) dan tiap huruf mirip angka (`_LOOKALIKE_RUN`)
    yang menempel digit atau penanda 1 ("8BB…2796", "ID…5678"). Baris ditandai bila jumlahnya >= MIN_RUN_DIGITS.
    Kata, spasi, dan tanda baca di antaranya tidak memisahkan: "Ref …5678 …1234" dan "ID Transaksi A1B2C3D4"
    ditandai (ruling A13 fix round 4) — salah tanda hanya satu lirikan di tinjauan A14, sedangkan yang lolos masuk
    ke korpus."""
    spans = _kept_spans(line)
    chars = list(line)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    blank = "".join(chars)
    lookalike = {i for m in _LOOKALIKE_RUN.finditer(blank) for i in range(*m.span())}
    for start, end in spans:
        if _is_number_fragment(line, blank, start, end, lookalike):
            chars[start:end] = line[start:end]
    text = "".join(chars)
    count = sum(c.isdecimal() for c in text)
    for m in _LOOKALIKE_RUN.finditer(text):
        a, b = m.span()
        if (a > 0 and text[a - 1].isdecimal()) or (b < len(text) and (text[b] == "…" or text[b].isdecimal())):
            count += b - a
    return count >= MIN_RUN_DIGITS


# ── Nama ────────────────────────────────────────────────────────────────────

# Nama samaran per peran (kata-katanya dipakai berurutan; nama yang lebih panjang memakai kata terakhir berulang).
PSEUDONYMS = {"user": "ANDI PRATAMA", "pihak": "BUDI SANTOSO", "pengirim": "SITI AMINAH", "merchant": "TOKO CONTOH"}
ROLES = ("pihak", "pengirim", "merchant", "user")   # urutan prioritas bila satu kata ada di nama dua peran
NAME_MIN_LETTERS = 2

_LETTER = r"[^\W\d_]"
_SPACE_SPLIT = re.compile(r"(\s+)")
_EDGE_PUNCT = re.compile(r"^(\W*)(.*?)(\W*)$", re.DOTALL)


def _normalize(s: str | None) -> str:
    """Sama dengan `merchants.normalize_name` (dipin tes): huruf kecil, tanda baca dibuang, spasi dirapatkan. Disalin
    supaya modul ini tidak memuat model/konfigurasi aplikasi."""
    if not s:
        return ""
    s = re.sub(r"[^\w\s]|_", "", s.lower())
    return " ".join(s.split())


def _name_words(name: str | None) -> list[tuple[int, str]]:
    """(urutan, kata nama huruf kecil >= NAME_MIN_LETTERS huruf): potongan nama pada spasi/tanda baca ("BUDI-SANTOSO" ->
    budi 0, santoso 1), lalu kata `_normalize` yang belum ada ("P.T." -> pt, "BUDI-SANTOSO" -> budisantoso 0)."""
    out: list[tuple[int, str]] = []
    seen: set[str] = set()
    for group in (re.split(r"[\W_]+", (name or "").lower()), _normalize(name).split()):
        for i, word in enumerate(w for w in group if w):
            if sum(c.isalpha() for c in word) >= NAME_MIN_LETTERS and word not in seen:
                seen.add(word)
                out.append((i, word))
    return out


def _cased(word: str, like: str) -> str:
    """`word` dengan huruf besar/kecil mengikuti `like`: BESAR, kecil, atau Kapital."""
    letters = [c for c in like if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return word.upper()
    if letters and all(c.islower() for c in letters):
        return word.lower()
    return word.capitalize()


def _word_map(names: dict[str, str | None]) -> dict[str, str]:
    """{kata nama (huruf kecil): kata samaran (huruf besar)}; kata ke-i nama memakai kata ke-i samaran perannya (yang
    terakhir bila habis). Peran di depan `ROLES` menang bila satu kata ada di dua nama."""
    mapping: dict[str, str] = {}
    for role in ROLES:
        fake = PSEUDONYMS[role].split()
        for i, word in _name_words(names.get(role)):
            mapping.setdefault(word, fake[min(i, len(fake) - 1)])
    return mapping


def _user_pseudonym(user_name: str | None) -> str | None:
    """Nama samaran user dengan jumlah kata (`_normalize`) dan huruf besar/kecil nama aslinya; None tanpa kata nama."""
    words = [w for w in (user_name or "").split() if sum(c.isalpha() for c in _normalize(w)) >= NAME_MIN_LETTERS]
    if not words:
        return None
    fake = PSEUDONYMS["user"].split()
    return " ".join(_cased(fake[min(i, len(fake) - 1)], w) for i, w in enumerate(words))


def pseudonymise(lines: list[str], names: dict[str, str | None]) -> tuple[list[str], str | None]:
    """Ganti setiap kata nama yang dikenal di setiap baris dengan kata samaran perannya (`PSEUDONYMS`; peran: `pihak`,
    `pengirim`, `merchant`, `user`; huruf besar/kecil mengikuti kata asli). Utuh kata: "budi" tidak mengganti potongan
    "BUDIMAN", tetapi mengganti "Ke:BUDI", "BUDI," dan "BUDI123"; token yang setelah `_normalize` sama dengan kata nama
    ("B.U.D.I", "BUDISANTOSO" untuk nama "Budi-Santoso") juga diganti utuh (tanda baca di ujungnya tetap).
    Mengembalikan (baris, nama samaran user atau None)."""
    mapping = _word_map(names)
    user = _user_pseudonym(names.get("user"))
    if not mapping:
        return list(lines), user
    alternatives = "|".join(re.escape(w) for w in sorted(mapping, key=len, reverse=True))
    rx = re.compile(rf"(?<!{_LETTER})(?:{alternatives})(?!{_LETTER})", re.IGNORECASE)

    def token(tok: str) -> str:
        if not tok or tok.isspace():
            return tok
        out = rx.sub(lambda m: _cased(mapping[m.group(0).lower()], m.group(0)), tok)
        if out != tok:
            return out
        lead, core, trail = _EDGE_PUNCT.match(tok).groups()
        fake = mapping.get(_normalize(core))
        return lead + _cased(fake, core) + trail if fake is not None else tok

    return ["".join(token(t) for t in _SPACE_SPLIT.split(line)) for line in lines], user
