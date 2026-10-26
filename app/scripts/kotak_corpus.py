"""Bagikan ke Jatahku — alat korpus bukti bayar dan gerbang akurasi rilis (spec §7a, §7c).

Korpus `app/tests/fixtures/kotak/corpus.json` berisi baris teks yang sudah disamarkan (bukan gambar
atau PDF asli) bersama hasil yang diharapkan. Sampel sintetis (`real: false`) selalu dievaluasi;
sampel nyata (`real: true`) hanya bila sudah ditinjau manusia (`reviewed: true`).

    python -m app.scripts.kotak_corpus add <file> --id <id> [--real] [--user-name NAMA] [--corpus PATH]
    python -m app.scripts.kotak_corpus eval [--real-only] [--corpus PATH]

`add` mengekstrak teks (OCR untuk gambar, lapisan teks/OCR untuk PDF, `.txt` apa adanya), menyamarkan
tiap baris (`mask_line`), menjalankan pembaca, lalu menambahkan sampel dengan `expect` = hasil pembaca
saat ini dan `reviewed: false`. Berkas asli tidak disalin. Periksa baris dan `expect` dengan bukti
aslinya, samarkan nama orang pribadi selain penerima/merchant, lalu set `"reviewed": true`.

`eval` mencetak hasil per sampel dan ringkasan, lalu keluar dengan kode 1 bila gerbang rilis tidak
lulus (atau korpus kosong). Lokal butuh `DATABASE_URL` dan `JWT_SECRET` di lingkungan (konfigurasi
aplikasi dimuat saat impor; alat ini tidak memakai database).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import re
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

from app.services.kotak_struk.extract import KIND_IMAGE, ExtractError, TextDoc, extract_text
from app.services.kotak_struk.readers.base import ParseContext
from app.services.kotak_struk.readers.labels import WIB
from app.services.kotak_struk.registry import read_document

DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "kotak" / "corpus.json"

GATE = {"amount_date_status_pct": 95.0, "counterparty_pct": 90.0, "doc_type_pct": 98.0}

PROOF_TYPES = ("qris", "transfer")
FIELDS = ("doc_type", "total", "date", "status", "flow", "counterparty")

_GATE_LABELS = {
    "amount_date_status_pct": "total/tanggal/status benar",
    "counterparty_pct": "pihak benar",
    "doc_type_pct": "doc_type benar",
}


# ── Penyamaran ──────────────────────────────────────────────────────────────

_MONTH_WORDS = {
    "januari", "january", "jan", "februari", "february", "feb", "peb", "maret", "march", "mar", "april", "apr",
    "mei", "may", "juni", "june", "jun", "juli", "july", "jul", "agustus", "august", "agu", "ags", "aug",
    "september", "sept", "sep", "oktober", "october", "okt", "oct", "november", "nopember", "nov", "nop",
    "desember", "december", "des", "dec",
}

# NMID QRIS (publik): "ID" + >= 10 digit.
_NMID = re.compile(r"(?<![A-Za-z0-9])ID\d{10,}")
# Nominal langsung sesudah Rp/IDR (spasi, titik, atau titik dua boleh): "Rp 1500000", "IDR150000", "Rp. 1.500.000,00".
_CURRENCY = re.compile(r"(?<![A-Za-z])(?:rp|idr)\s*[.:]?\s*\d[\d.,]*", re.IGNORECASE)
# Tanggal angka dengan pemisah yang sama: d-m-y, d/m/y, d.m.y (tahun 2 atau 4 digit) dan y-m-d. Tidak boleh
# menempel pada deret angka lain ("1234-12-10-26" bukan tanggal, melainkan nomor yang harus disamarkan).
_DATE_DMY = re.compile(r"(?<!\d)(?<!\d[-/.])(\d{1,2})([-/.])(\d{1,2})\2(\d{4}|\d{2})(?![-/.]?\d)")
_DATE_YMD = re.compile(r"(?<!\d)(?<!\d[-/.])(\d{4})([-/.])(\d{1,2})\2(\d{1,2})(?![-/.]?\d)")
# Tanggal dengan nama bulan di depan ("Oct 26 2026", "Okt 26, 2026"): hari dan tahun hanya dipisah spasi.
_DATE_MDY = re.compile(r"(?<![A-Za-z])([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)")
# Jam: 08:12, 08:12:33, 08.12.33.
_TIME = re.compile(r"(?<![\d:.])(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?(?!\d|[:.]\d)")
# Nominal berkelompok ribuan, dengan desimal opsional: 1.500.000, 150,000.00, 1.500.000,00.
_GROUPED = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?(?!\d|[.,]\d)")
# Deret digit: kelompok digit yang dipisah satu spasi atau satu strip.
_DIGIT_RUN = re.compile(r"\d+(?:[ -]\d+)*")


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
    (_NMID, None), (_CURRENCY, None), (_DATE_DMY, _dmy_ok), (_DATE_YMD, _ymd_ok), (_DATE_MDY, _mdy_ok),
    (_TIME, _time_ok), (_GROUPED, None),
)


def _kept_spans(line: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for rx, valid in _KEEP:
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
        return "…" + digits[-4:] if len(digits) >= 6 else m.group()
    return _DIGIT_RUN.sub(repl, text)


def mask_line(line: str) -> str:
    """Samarkan nomor rekening, nomor referensi, nomor HP, dan deret angka panjang lain di satu baris.

    Deret >= 6 digit (boleh dipisah satu spasi atau satu strip antarkelompok) menjadi `…` + 4 digit
    terakhirnya. Dibiarkan: nominal (berkelompok ribuan, atau langsung sesudah Rp/IDR), tanggal
    (d-m-y, d/m/y, d.m.y, y-m-d, dan "Oct 26 2026"), jam, dan NMID (`ID` + >= 10 digit, publik).
    Teks yang sudah tersamar (`…4567`, `****1234`) tidak berubah."""
    out, pos = [], 0
    for start, end in _kept_spans(line):
        out.append(_mask_runs(line[pos:start]))
        out.append(line[start:end])
        pos = end
    out.append(_mask_runs(line[pos:]))
    return "".join(out)


# ── Evaluasi ────────────────────────────────────────────────────────────────

def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _wib_date(value) -> date | None:
    """Tanggal kalender WIB dari datetime/ISO string; tanpa zona dianggap sudah WIB."""
    dt = _parse_iso(value)
    if dt is None:
        return None
    return dt.astimezone(WIB).date() if dt.tzinfo else dt.date()


def _wib_today() -> date:
    return datetime.now(WIB).date()


def sample_context(sample: dict) -> ParseContext:
    """Konteks baca satu sampel: `today` dari sampel, lalu tanggal WIB `paid_at` yang diharapkan, lalu hari ini.
    Pembaca menebak tahun yang tidak tertulis dari `today`, jadi hasil evaluasi tidak boleh ikut kalender."""
    if sample.get("today"):
        today = date.fromisoformat(sample["today"])
    else:
        today = _wib_date((sample.get("expect") or {}).get("paid_at")) or _wib_today()
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


def _field(expected, actual, ok: bool) -> dict:
    return {"ok": ok, "expected": expected, "actual": actual}


def _compare(sample: dict, doc) -> dict:
    e = sample.get("expect") or {}
    exp_date, act_date = _wib_date(e.get("paid_at")), _wib_date(doc.paid_at)
    exp_total = e.get("total")
    fields = {
        "doc_type": _field(e.get("doc_type"), doc.doc_type, e.get("doc_type") == doc.doc_type),
        "total": _field(exp_total, doc.amounts.total,
                        (exp_total is None and doc.amounts.total is None)
                        or (exp_total is not None and doc.amounts.total is not None
                            and int(exp_total) == int(doc.amounts.total))),
        "date": _field(exp_date.isoformat() if exp_date else None, act_date.isoformat() if act_date else None,
                       exp_date == act_date),
        "status": _field(e.get("status"), doc.status, e.get("status") == doc.status),
        "flow": _field(e.get("flow"), doc.flow, e.get("flow") == doc.flow),
        "counterparty": _field(e.get("counterparty"), doc.counterparty.name,
                               _name(e.get("counterparty")) == _name(doc.counterparty.name)),
    }
    return {"id": sample["id"], "fields": fields, "ok": all(f["ok"] for f in fields.values())}


def _pct(good: int, total: int) -> float | None:
    """Persen dengan 1 desimal, dibulatkan ke bawah supaya pembulatan tidak pernah meloloskan gerbang."""
    return None if total == 0 else (1000 * good // total) / 10


def evaluate(samples: list[dict]) -> dict:
    """Bandingkan hasil pembaca dengan `expect` tiap sampel (sinkron; pembaca dijalankan lewat asyncio.run).

    Persen total/tanggal/status, pihak, dan arah dihitung atas sampel yang diharapkan `qris`/`transfer`
    (None bila tidak ada); `doc_type` atas semua sampel. `struk_as_proof` = struk belanja yang terbaca
    sebagai bukti bayar; `failures` = sampel dengan salah satu field berbeda, urut seperti di korpus."""
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
        "struk_as_proof": [s["id"] for s, t, d in zip(samples, expected, docs)
                           if t == "struk_belanja" and d.doc_type in PROOF_TYPES],
        "failures": [r["id"] for r in rows if not r["ok"]],
        "rows": rows,
    }


def gate_failures(result: dict) -> list[str]:
    """Alasan gerbang rilis (spec §7c) tidak lulus; kosong = lulus. `flow_pct` dilaporkan, tidak digerbang."""
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

def load_corpus(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["samples"]


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
    """Tulis atomik (berkas sementara di folder yang sama, lalu ganti)."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".corpus-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(format_corpus(samples))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
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


def _expect_from(doc) -> dict:
    paid_at = doc.paid_at
    if paid_at is not None:
        paid_at = (paid_at.astimezone(WIB) if paid_at.tzinfo else paid_at.replace(tzinfo=WIB)).isoformat(timespec="seconds")
    return {
        "doc_type": doc.doc_type, "total": doc.amounts.total, "paid_at": paid_at,
        "counterparty": doc.counterparty.name or None, "status": doc.status, "flow": doc.flow,
    }


def _err(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def cmd_add(args) -> int:
    corpus_path = Path(args.corpus)
    samples = load_corpus(corpus_path)
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
    doc = asyncio.run(_read(sample))
    sample["expect"] = _expect_from(doc)
    write_corpus(corpus_path, [*samples, sample])

    print(f"Sampel {args.id} ditambahkan ke {corpus_path} ({text.kind}, {len(lines)} baris).")
    print("Baris (tersamar):")
    for i, line in enumerate(lines, 1):
        print(f"  {i:>2}. {line}")
    print("expect (hasil pembaca saat ini):")
    print("  " + _dumps(sample["expect"]))
    if args.real:
        print('Periksa baris dan expect dengan bukti aslinya, samarkan nama orang pribadi selain penerima/merchant, '
              'lalu set "reviewed": true.')
    return 0


def _ok(flag: bool) -> str:
    return "ok" if flag else "✗"


def _fmt_pct(value) -> str:
    return "—" if value is None else f"{value}%"


def _print_report(samples: list[dict], result: dict) -> None:
    width = max([len("id"), *(len(s["id"]) for s in samples)])
    heads = ("doc_type", "total", "tanggal", "status", "flow", "pihak")
    print((f"{'id':<{width}}  " + "  ".join(f"{h:<8}" for h in heads)).rstrip())
    for row in result["rows"]:
        print((f"{row['id']:<{width}}  " + "  ".join(f"{_ok(row['fields'][k]['ok']):<8}" for k in FIELDS)).rstrip())
        for key in FIELDS:
            field = row["fields"][key]
            if not field["ok"]:
                print(f"{'':<{width}}    ✗ {key}: diharapkan {_dumps(field['expected'])}, terbaca {_dumps(field['actual'])}")
    print()
    print(f"Ringkasan (n={result['n']})")
    for key, label in _GATE_LABELS.items():
        print(f"  {label:<28} {_fmt_pct(result[key]):>7}  (gerbang ≥{GATE[key]}%)")
    print(f"  {'flow benar':<28} {_fmt_pct(result['flow_pct']):>7}  (tidak digerbang)")
    print("  struk belanja terbaca sebagai bukti bayar: " + (", ".join(result["struk_as_proof"]) or "-"))
    print("  gagal: " + (", ".join(result["failures"]) or "-"))


def cmd_eval(args) -> int:
    corpus_path = Path(args.corpus)
    samples = load_corpus(corpus_path)
    unreviewed = sum(1 for s in samples if s.get("real") and not s.get("reviewed"))
    if args.real_only:
        chosen = [s for s in samples if s.get("real") and s.get("reviewed")]
    else:
        chosen = [s for s in samples if not s.get("real") or s.get("reviewed")]
    synthetic = sum(1 for s in chosen if not s.get("real"))
    print(f"Korpus {corpus_path}: {len(chosen)} sampel ({synthetic} sintetis, {len(chosen) - synthetic} nyata); "
          f"{unreviewed} sampel nyata belum ditinjau dilewati")
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
    a.add_argument("--user-name", help="nama akun user untuk cek arah 'antar rekening sendiri'")
    a.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    e = sub.add_parser("eval", help="evaluasi pembaca terhadap korpus dan cek gerbang rilis")
    e.add_argument("--real-only", action="store_true", help="hanya sampel nyata yang sudah ditinjau")
    e.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    args = ap.parse_args(argv)
    return cmd_add(args) if args.perintah == "add" else cmd_eval(args)


if __name__ == "__main__":
    sys.exit(main())
