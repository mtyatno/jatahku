"""Bagikan ke Jatahku — alat korpus bukti bayar dan gerbang akurasi rilis (spec §7a, §7c).

Korpus `app/tests/fixtures/kotak/corpus.json` berisi baris teks yang sudah disamarkan (bukan gambar
atau PDF asli) bersama hasil yang diharapkan. Sampel sintetis (`real: false`) selalu dievaluasi;
sampel nyata (`real: true`) hanya bila sudah ditinjau manusia (`reviewed: true`). Evaluasi bawaan juga
memuat 4 struk Indomaret asli dari `app/tests/fixtures/receipt_ocr_lines.json` (harus tetap `struk_belanja`).

    python -m app.scripts.kotak_corpus add <file> --id <id> [--real] [--user-name NAMA] [--corpus PATH]
    python -m app.scripts.kotak_corpus eval [--real-only] [--corpus PATH]

`add` mengekstrak teks (OCR untuk gambar, lapisan teks/OCR untuk PDF, `.txt` apa adanya), menyamarkan
tiap baris (`mask_line`), menjalankan pembaca pada baris tersamar, lalu menambahkan sampel dengan
`expect` = hasil pembaca saat ini dan `reviewed: false`. Berkas asli tidak disalin. Baris yang masih memuat
>= 6 digit di luar bentuk yang dibiarkan dicetak sebagai `PERIKSA baris N`. Periksa baris dan `expect` dengan
bukti aslinya, samarkan nama orang pribadi (juga `user_name`), lalu set `"reviewed": true`.

`eval` mencetak hasil per sampel dan ringkasan, lalu keluar dengan kode 1 bila gerbang rilis tidak
lulus (atau tidak ada sampel), 2 bila berkas korpus tidak ada atau rusak.
"""
from __future__ import annotations

import os

# Alat ini tidak membuka database, tetapi impor pembaca memuat konfigurasi aplikasi yang mewajibkan dua nilai ini
# (seperti `openapi_cek._env()`). Nilai yang sudah ada di lingkungan tidak diubah.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "kotak-corpus")

import argparse  # noqa: E402
import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import mimetypes  # noqa: E402
import re  # noqa: E402
import stat  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from datetime import date, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from app.services.kotak_struk.extract import KIND_IMAGE, ExtractError, TextDoc, extract_text  # noqa: E402
from app.services.kotak_struk.readers.base import ParseContext  # noqa: E402
from app.services.kotak_struk.readers.labels import WIB  # noqa: E402
from app.services.kotak_struk.registry import read_document  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
DEFAULT_CORPUS = _FIXTURES / "kotak" / "corpus.json"
RECEIPTS_FIXTURE = _FIXTURES / "receipt_ocr_lines.json"

GATE = {"amount_date_status_pct": 95.0, "counterparty_pct": 90.0, "doc_type_pct": 98.0}

PROOF_TYPES = ("qris", "transfer")
# Urutan kolom laporan. `date` dibandingkan dengan kunci `paid_at` di expect.
FIELDS = ("doc_type", "issuer", "total", "date", "status", "flow", "counterparty")
_PROOF_FIELDS = ("total", "date", "status", "flow", "counterparty")   # wajib ada di expect bukti bayar
_EXPECT_KEY = {"date": "paid_at"}

_GATE_LABELS = {
    "amount_date_status_pct": "total/tanggal/status benar",
    "counterparty_pct": "pihak benar",
    "doc_type_pct": "doc_type benar",
}


# ── Penyamaran ──────────────────────────────────────────────────────────────

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


def _time_ok(m: re.Match) -> bool:
    return int(m.group(1)) <= 23 and int(m.group(2)) <= 59 and int(m.group(3) or 0) <= 59


# Urutan = prioritas: rentang yang ditemukan lebih dulu menang bila bertumpang tindih.
_KEEP = (
    (_CURRENCY, None), (_DATE_DMY, _dmy_ok), (_DATE_YMD, _ymd_ok), (_DATE_MDY, _mdy_ok), (_TIME, _time_ok),
    (_GROUPED, None),
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
    "Oct 26 2026"), jam, dan NMID (`ID` + >= 10 digit) di baris berlabel NMID. Teks yang sudah tersamar
    (`…4567`, `****1234`) tidak berubah."""
    out, pos = [], 0
    for start, end in _kept_spans(line):
        out.append(_mask_runs(line[pos:start]))
        out.append(line[start:end])
        pos = end
    out.append(_mask_runs(line[pos:]))
    return "".join(out)


_MASKED_TOKEN = re.compile(r"…\d{4}")       # keluaran mask_line; digit sesudahnya (bila ada) tetap digit lepas
_LONE_TOKEN = re.compile(r"(?<!\S)…\d{4}(?!\S)")   # dipisah spasi (atau awal/akhir baris) di kedua sisi
_WORD = re.compile(r"[^\W\d_]{2,}")
_DIGIT = re.compile(r"\d")
# Dua penanda dari satu nomor yang terpotong: dipisah >= 3 spasi, atau "/", ":", "_" (boleh diapit spasi). Satu-dua
# spasi tidak: "Ref …5678 …1234" adalah cara bank mencetak nilai yang sudah tersamar, dan satu-dua spasi di dalam satu
# nomor sudah membuatnya satu deret.
_TOKEN_PAIR = re.compile(rf"…\d{{4}}(?:{_HWS}{{3,}}|{_HWS}*[/:_]{_HWS}*)…\d{{4}}")


def _chunk_needs_review(chunk: str) -> bool:
    total = len(_DIGIT.findall(chunk))   # penanda `…dddd` ikut dihitung 4 digit
    if total < MIN_RUN_DIGITS:
        return False
    bare = len(_DIGIT.findall(_MASKED_TOKEN.sub(" ", chunk)))
    glued = len(_MASKED_TOKEN.findall(chunk)) > len(_LONE_TOKEN.findall(chunk))
    return bool(bare) or glued


def needs_review(line: str) -> bool:
    """Jaring pengaman untuk tinjauan manusia: apakah baris (sesudah `mask_line`) mungkin masih menampilkan >= 6
    digit sebuah nomor? Bentuk yang dibiarkan (nominal, tanggal, jam, NMID) diabaikan. Digit dihitung melintasi
    pemisah apa pun yang bukan kata (/, :, _, spasi, satu huruf salah-baca OCR seperti "4S6"); kata >= 2 huruf
    memisahkan. Penanda `…dddd` dihitung 4 digit: potongan dengan >= 6 digit ditandai bila masih ada digit lepas di
    sampingnya ("…1234S6 7890") atau penanda yang menempel ("…8472B …4242"); penanda yang berdiri sendiri
    ("…5678 …1234") tidak, kecuali dua penanda yang dipisah >= 3 spasi atau "/", ":", "_" ("…3091 / …3755": satu
    nomor yang terpotong). Tidak pernah memblokir."""
    if _TOKEN_PAIR.search(line):   # pada baris asli: tanggal/jam/nominal di antaranya tetap memisahkan
        return True
    parts, pos = [], 0
    for start, end in _kept_spans(line):
        parts.append(line[pos:start])
        parts.append(" ")
        pos = end
    parts.append(line[pos:])
    return any(_chunk_needs_review(chunk) for chunk in _WORD.split("".join(parts)))


# ── Evaluasi ────────────────────────────────────────────────────────────────

def _wib_date(value) -> date | None:
    """Tanggal kalender WIB dari datetime/ISO string; tanpa zona dianggap sudah WIB."""
    if not value:
        return None
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return dt.astimezone(WIB).date() if dt.tzinfo else dt.date()


def _expected_date(value) -> tuple[date | None, str | None]:
    """(tanggal WIB, alasan bila `paid_at` di expect tidak sah)."""
    if value is not None and not isinstance(value, str):
        return None, "expect.paid_at harus teks tanggal-jam ISO atau null"
    try:
        return _wib_date(value), None
    except ValueError:
        return None, "expect.paid_at bukan tanggal-jam ISO"


def _wib_today() -> date:
    return datetime.now(WIB).date()


def sample_context(sample: dict) -> ParseContext:
    """Konteks baca satu sampel: `today` dari sampel, lalu tanggal WIB `paid_at` yang diharapkan, lalu hari ini.
    Pembaca menebak tahun yang tidak tertulis dari `today`, jadi hasil evaluasi tidak boleh ikut kalender."""
    if sample.get("today"):
        today = date.fromisoformat(sample["today"])
    else:
        today = _expected_date((sample.get("expect") or {}).get("paid_at"))[0] or _wib_today()
    return ParseContext(today=today, user_name=sample.get("user_name"))


def _name(value) -> str | None:
    text = " ".join(str(value or "").split()).casefold()
    return text or None


async def _read(sample: dict):
    # Pembaca tidak membedakan `kind`; "image" seperti di test_kotak_readers.
    doc = TextDoc(lines=list(sample.get("lines") or []), kind=KIND_IMAGE)
    return (await read_document(doc, sample_context(sample), proofs_enabled=True)).parsed.doc


async def _read_all(samples: list[dict]) -> list:
    return [await _read(s) for s in samples]


def _field(expected, actual, ok: bool, reason: str | None = None) -> dict:
    out = {"ok": ok, "expected": expected, "actual": actual}
    if reason:
        out["reason"] = reason
    return out


def _actual(name: str, doc):
    if name == "total":
        return doc.amounts.total
    if name == "date":
        d = _wib_date(doc.paid_at)
        return d.isoformat() if d else None
    if name == "counterparty":
        return doc.counterparty.name
    return getattr(doc, name)


def _compare_field(name: str, expected, doc) -> dict:
    actual = _actual(name, doc)
    if name == "total":
        if expected is not None and (type(expected) is not int):
            return _field(expected, actual, False, "expect.total harus bilangan bulat atau null")
        return _field(expected, actual, expected == actual)
    if name == "date":
        exp_date, reason = _expected_date(expected)
        if reason:
            return _field(expected, actual, False, reason)
        exp_text = exp_date.isoformat() if exp_date else None
        return _field(exp_text, actual, exp_text == actual)
    if name == "counterparty":
        return _field(expected, actual, _name(expected) == _name(actual))
    return _field(expected, actual, expected == actual)


def _compare(sample: dict, doc) -> dict:
    """Bandingkan satu sampel. `doc_type` selalu; `issuer` bila ada di expect; total/tanggal/status/arah/pihak
    bila ada di expect, dan wajib ada untuk bukti bayar (tidak ada = salah). Struk Indomaret hanya `doc_type`."""
    e = sample.get("expect") or {}
    proof = e.get("doc_type") in PROOF_TYPES
    fields = {"doc_type": _field(e.get("doc_type"), doc.doc_type, e.get("doc_type") == doc.doc_type)}
    if "issuer" in e:
        fields["issuer"] = _field(e["issuer"], doc.issuer, e["issuer"] == doc.issuer)
    for name in _PROOF_FIELDS:
        key = _EXPECT_KEY.get(name, name)
        if key in e:
            fields[name] = _compare_field(name, e[key], doc)
        elif proof:
            fields[name] = _field(None, _actual(name, doc), False, f"expect.{key} tidak ada")
    return {"id": sample["id"], "fields": fields, "ok": all(f["ok"] for f in fields.values())}


def _pct(good: int, total: int) -> float | None:
    """Persen dengan 1 desimal, dibulatkan ke bawah supaya pembulatan tidak pernah meloloskan gerbang."""
    return None if total == 0 else (1000 * good // total) / 10


def evaluate(samples: list[dict]) -> dict:
    """Bandingkan hasil pembaca dengan `expect` tiap sampel (sinkron; pembaca dijalankan lewat asyncio.run).

    Persen total/tanggal/status, pihak, dan arah dihitung atas sampel yang diharapkan `qris`/`transfer`
    (None bila tidak ada); `doc_type` atas semua sampel; `issuer` atas sampel yang punya `issuer` di expect.
    `struk_as_proof` = struk belanja yang terbaca sebagai bukti bayar; `failures` = sampel dengan salah satu
    field berbeda, urut seperti masukan."""
    docs = asyncio.run(_read_all(samples))
    rows = [_compare(s, d) for s, d in zip(samples, docs)]
    expected = [(s.get("expect") or {}).get("doc_type") for s in samples]
    proofs = [r for t, r in zip(expected, rows) if t in PROOF_TYPES]

    def share(group: list[dict], *keys: str) -> float | None:
        return _pct(sum(all(r["fields"][k]["ok"] for k in keys) for r in group), len(group))

    return {
        "n": len(rows),
        "amount_date_status_pct": share(proofs, "total", "date", "status"),
        "counterparty_pct": share(proofs, "counterparty"),
        "doc_type_pct": share(rows, "doc_type"),
        "flow_pct": share(proofs, "flow"),
        "issuer_pct": share([r for r in rows if "issuer" in r["fields"]], "issuer"),
        "struk_as_proof": [s["id"] for s, t, d in zip(samples, expected, docs)
                           if t == "struk_belanja" and d.doc_type in PROOF_TYPES],
        "failures": [r["id"] for r in rows if not r["ok"]],
        "rows": rows,
    }


def gate_failures(result: dict) -> list[str]:
    """Alasan gerbang rilis (spec §7c) tidak lulus; kosong = lulus. `flow_pct` dan `issuer_pct` dilaporkan,
    tidak digerbang."""
    reasons = []
    for key, minimum in GATE.items():
        value = result.get(key)
        if value is None:
            what = "sampel" if key == "doc_type_pct" else "sampel QRIS/transfer"
            reasons.append(f"{key}: tidak ada {what}")
        elif value < minimum:
            reasons.append(f"{key} {value}% < {minimum}%")
    if result.get("struk_as_proof"):
        reasons.append("struk belanja terbaca sebagai bukti bayar: " + ", ".join(result["struk_as_proof"]))
    return reasons


# ── Berkas korpus ───────────────────────────────────────────────────────────

class CorpusError(Exception):
    """Berkas korpus (atau fixture struk) tidak ada atau rusak; pesannya aman dicetak."""


def load_corpus(path: Path) -> list[dict]:
    path = Path(path)
    if not path.parent.is_dir():
        raise CorpusError(f"folder korpus tidak ada: {path.parent}")
    if not path.is_file():
        raise CorpusError(f"berkas korpus tidak ada: {path} (periksa --corpus)")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise CorpusError(f"berkas korpus tidak bisa dibaca: {path} ({e})") from e
    except ValueError as e:   # JSONDecodeError, UnicodeDecodeError
        raise CorpusError(f"berkas korpus rusak: {path} ({e})") from e
    samples = data.get("samples") if isinstance(data, dict) else None
    if not isinstance(samples, list):
        raise CorpusError(f'berkas korpus rusak: {path} (harus {{"samples": [...]}})')
    seen: set[str] = set()
    for i, sample in enumerate(samples, 1):
        problem = _sample_problem(sample)
        where = f"sampel ke-{i}" + (f" ({sample['id']})" if isinstance(sample, dict) and isinstance(sample.get("id"), str)
                                    and sample["id"] else "")
        if problem:
            raise CorpusError(f"berkas korpus rusak: {path}, {where}: {problem}")
        if sample["id"] in seen:
            raise CorpusError(f"berkas korpus rusak: {path}, {where}: id ganda")
        seen.add(sample["id"])
    return samples


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _sample_problem(sample) -> str | None:
    """Isi sampel yang diedit tangan: tipe tiap field (mis. `"reviewed": "false"` adalah teks, dan bernilai benar)."""
    if not isinstance(sample, dict):
        return "harus objek"
    if not isinstance(sample.get("id"), str) or not sample["id"]:
        return '"id" harus teks yang tidak kosong'
    if type(sample.get("real")) is not bool:
        return '"real" harus true atau false'
    if "reviewed" in sample and type(sample["reviewed"]) is not bool:
        return '"reviewed" harus true atau false'
    if "today" in sample:
        today = sample["today"]
        try:
            if not isinstance(today, str) or not _ISO_DATE.fullmatch(today):
                raise ValueError
            date.fromisoformat(today)
        except ValueError:
            return '"today" harus tanggal ISO (YYYY-MM-DD)'
    if "user_name" in sample and not isinstance(sample["user_name"], str):
        return '"user_name" harus teks'
    lines = sample.get("lines")
    if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
        return '"lines" harus daftar teks'
    if not isinstance(sample.get("expect"), dict):
        return '"expect" harus objek'
    return None


def receipt_samples(path: Path = RECEIPTS_FIXTURE) -> list[dict]:
    """Struk Indomaret asli yang sudah ada (spec §7a) sebagai sampel `struk_belanja`: hanya `doc_type` (dan
    `struk_as_proof`) yang berlaku. `today` = tanggal struk, supaya evaluasi tidak ikut kalender."""
    path = Path(path)
    try:
        receipts = json.loads(path.read_text(encoding="utf-8"))["receipts"]
        out = []
        for rec in receipts:
            sample = {"id": f"indomaret-{rec['id']}", "real": True, "reviewed": True}
            when = (rec.get("expect") or {}).get("date")
            if when:
                sample["today"] = when
            sample["lines"] = list(rec["lines"])
            sample["expect"] = {"doc_type": "struk_belanja"}
            out.append(sample)
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise CorpusError(f"fixture struk Indomaret tidak bisa dibaca: {path} ({e!r})") from e
    return out


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def format_corpus(samples: list[dict]) -> str:
    """Tata letak buatan tangan fixture: satu sampel = baris data (tanpa `expect`) + baris `expect`."""
    blocks = []
    for sample in samples:
        head = {k: v for k, v in sample.items() if k != "expect"}
        if "expect" in sample:
            blocks.append(f"  {_dumps(head)[:-1]},\n   \"expect\": {_dumps(sample['expect'])}}}")
        else:
            blocks.append(f"  {_dumps(head)}")
    return '{"samples": [\n' + "".join(b + ",\n" for b in blocks[:-1]) + (blocks[-1] + "\n" if blocks else "") + "]}\n"


def write_corpus(path: Path, samples: list[dict]) -> None:
    """Tulis atomik (berkas sementara di folder yang sama, lalu ganti). Bit izin berkas lama dipertahankan
    (mkstemp membuat 0600); berkas baru 0644."""
    path = Path(path)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(prefix=".corpus-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(format_corpus(samples))
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


# ── CLI ─────────────────────────────────────────────────────────────────────

def _content_type(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext == ".txt":
        return "text/plain"
    if ext == ".pdf":
        return "application/pdf"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed if guessed and guessed.startswith("image/") else None


def expect_from(doc) -> dict:
    """Hasil pembaca dalam bentuk `expect` korpus (urutan kunci seperti spec §7a)."""
    paid_at = doc.paid_at
    if paid_at is not None:
        paid_at = (paid_at.astimezone(WIB) if paid_at.tzinfo else paid_at.replace(tzinfo=WIB)).isoformat(timespec="seconds")
    return {
        "doc_type": doc.doc_type, "issuer": doc.issuer or None, "total": doc.amounts.total, "paid_at": paid_at,
        "counterparty": doc.counterparty.name or None, "status": doc.status, "flow": doc.flow,
    }


def _err(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


_NAME_REMINDER = ("Nama orang pribadi: samarkan di baris (selain penerima/merchant yang dibutuhkan) dan di user_name. "
                  "user_name dan nama penerima transfer ke rekening sendiri adalah nama pribadi — ganti keduanya "
                  "dengan nama samaran yang sama.")
# Dua hal yang tidak bisa dideteksi alat ini (penyamaran per baris, aturan >= 6 digit): hanya tinjauan manusia.
_LIMITS_REMINDER = ("Yang tidak terdeteksi alat ini, cek sendiri: nomor yang terpotong ke dua baris (mis. \"61234\" lalu "
                    "\"…8812\" di baris berikutnya) dan nomor referensi campuran huruf dan angka pendek "
                    "(mis. \"TRX61234AB5678\") — samarkan dengan tangan.")


def cmd_add(args) -> int:
    corpus_path = Path(args.corpus)
    try:
        samples = load_corpus(corpus_path)   # sebelum ekstraksi: salah ketik --corpus tidak membuang waktu OCR
    except CorpusError as e:
        return _err(str(e))
    if any(s.get("id") == args.id for s in samples):
        return _err(f"id {args.id!r} sudah ada di {corpus_path}; pakai id lain.")
    source = Path(args.file)
    content_type = _content_type(source)
    if content_type is None:
        return _err(f"jenis berkas tidak didukung: {source.name} (pakai .txt, .pdf, atau gambar)")
    try:
        data = source.read_bytes()
    except OSError as e:
        return _err(f"berkas tidak bisa dibaca: {e}")
    try:
        text = asyncio.run(extract_text(data, content_type))
    except ExtractError as e:
        cause = f" ({e.__cause__!r})" if e.__cause__ else ""
        return _err(e.user_message + cause)

    lines = [mask_line(line) for line in text.lines]
    sample: dict = {"id": args.id, "real": bool(args.real)}
    if args.real:
        sample["reviewed"] = False
    sample["today"] = _wib_today().isoformat()
    if args.user_name:
        sample["user_name"] = args.user_name
    sample["lines"] = lines
    sample["expect"] = expect_from(asyncio.run(_read(sample)))   # dibaca dari baris tersamar, seperti `eval`
    write_corpus(corpus_path, [*samples, sample])

    print(f"Sampel {args.id} ditambahkan ke {corpus_path} ({text.kind}, {len(lines)} baris).")
    print("Baris (tersamar):")
    for i, line in enumerate(lines, 1):
        print(f"  {i:>2}. {line}")
    print("expect (hasil pembaca saat ini):")
    print("  " + _dumps(sample["expect"]))
    flagged = [(i, line) for i, line in enumerate(lines, 1) if needs_review(line)]
    if flagged:
        print("Baris yang masih memuat >= 6 digit (cek nomor rekening/referensi/HP yang belum tersamar):")
        for i, line in flagged:
            print(f"PERIKSA baris {i}: {line}")
    if args.real:
        print('Periksa baris dan expect dengan bukti aslinya, lalu set "reviewed": true.')
    print(_NAME_REMINDER)
    print(_LIMITS_REMINDER)
    return 0


def _cell(row: dict, key: str) -> str:
    field = row["fields"].get(key)
    return "-" if field is None else ("ok" if field["ok"] else "✗")


def _fmt_pct(value) -> str:
    return "—" if value is None else f"{value}%"


def _print_report(samples: list[dict], result: dict) -> None:
    width = max([len("id"), *(len(s["id"]) for s in samples)])
    heads = ("doc_type", "issuer", "total", "tanggal", "status", "flow", "pihak")
    print((f"{'id':<{width}}  " + "  ".join(f"{h:<8}" for h in heads)).rstrip())
    for row in result["rows"]:
        print((f"{row['id']:<{width}}  " + "  ".join(f"{_cell(row, k):<8}" for k in FIELDS)).rstrip())
        for key in FIELDS:
            field = row["fields"].get(key)
            if field is not None and not field["ok"]:
                reason = f" — {field['reason']}" if field.get("reason") else ""
                print(f"{'':<{width}}    ✗ {key}: diharapkan {_dumps(field['expected'])}, "
                      f"terbaca {_dumps(field['actual'])}{reason}")
    print()
    print(f"Ringkasan (n={result['n']})")
    for key, label in _GATE_LABELS.items():
        print(f"  {label:<28} {_fmt_pct(result[key]):>7}  (gerbang ≥{GATE[key]}%)")
    print(f"  {'flow benar':<28} {_fmt_pct(result['flow_pct']):>7}  (tidak digerbang)")
    print(f"  {'issuer benar':<28} {_fmt_pct(result['issuer_pct']):>7}  (tidak digerbang)")
    print("  struk belanja terbaca sebagai bukti bayar: " + (", ".join(result["struk_as_proof"]) or "-"))
    print("  gagal: " + (", ".join(result["failures"]) or "-"))


def cmd_eval(args) -> int:
    corpus_path = Path(args.corpus)
    try:
        samples = load_corpus(corpus_path)
        receipts = [] if args.real_only else receipt_samples()
    except CorpusError as e:
        return _err(str(e))
    unreviewed = sum(1 for s in samples if s.get("real") and not s.get("reviewed"))
    if args.real_only:
        chosen = [s for s in samples if s.get("real") and s.get("reviewed")]
    else:
        chosen = [s for s in samples if not s.get("real") or s.get("reviewed")]
    synthetic = sum(1 for s in chosen if not s.get("real"))
    real = len(chosen) - synthetic
    chosen = chosen + receipts
    print(f"Korpus {corpus_path}: {len(chosen)} sampel ({synthetic} sintetis, {real} nyata, "
          f"{len(receipts)} struk Indomaret); {unreviewed} sampel nyata belum ditinjau dilewati")
    if not chosen:
        print("korpus nyata belum ada")
        return 1
    print()
    result = evaluate(chosen)
    _print_report(chosen, result)
    reasons = gate_failures(result)
    print()
    if reasons:
        print("Gerbang rilis: TIDAK LULUS")
        for reason in reasons:
            print(f"  - {reason}")
        return 1
    print("Gerbang rilis: lulus")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="perintah", required=True)
    a = sub.add_parser("add", help="tambahkan satu bukti (tersamar) ke korpus")
    a.add_argument("file")
    a.add_argument("--id", required=True)
    a.add_argument("--real", action="store_true", help="bukti nyata (perlu ditinjau sebelum dievaluasi)")
    a.add_argument("--user-name", help="nama akun user untuk cek arah 'antar rekening sendiri' (pakai nama samaran)")
    a.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    e = sub.add_parser("eval", help="evaluasi pembaca terhadap korpus dan cek gerbang rilis")
    e.add_argument("--real-only", action="store_true", help="hanya sampel nyata yang sudah ditinjau")
    e.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    args = ap.parse_args(argv)
    return cmd_add(args) if args.perintah == "add" else cmd_eval(args)


if __name__ == "__main__":
    sys.exit(main())
