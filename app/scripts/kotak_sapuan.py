"""Kotak Struk — snapshot sapuan pembaca (spec §9.1): penjaga "tidak ada struk belanja berubah, tidak ada blokir hilang".

`app/tests/fixtures/kotak/sweep_lines.json` berisi daftar baris OCR (hanya disalin dari tes dan fixture yang sudah ada;
repo publik) bertanda `store`, `store_void`, `store_pending`, `proof`, `failed`, `pending`, `probe`, dan `known_<item>`
(temuan terbuka dengan alasan di `note`). Setiap daftar dibaca seperti worker (`read_document` lalu `worker._outcome`)
dengan saklar `receipt_inbox` mati dan menyala, tanggal tetap 1 Nov 2026, tanpa aturan belajar. Hasilnya disimpan di
`app/tests/fixtures/kotak/sweep_snapshot.json` dan dibandingkan oleh `app/tests/test_kotak_sapuan.py`.

    python -m app.scripts.kotak_sapuan cek  [--lines PATH] [--snapshot PATH]   # cetak beda; exit 1 bila ada beda
    python -m app.scripts.kotak_sapuan tulis [--lines PATH] [--snapshot PATH]  # tulis ulang snapshot

Perubahan pembaca yang disengaja: jalankan `cek`, cantumkan bedanya di laporan task, lalu `tulis`.
"""
from __future__ import annotations

import os

# Alat ini tidak membuka database, tetapi impor pembaca/worker memuat konfigurasi aplikasi yang mewajibkan dua nilai
# ini (seperti `kotak_corpus`). Nilai yang sudah ada di lingkungan tidak diubah.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "kotak-sapuan")

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

from app.services.kotak_struk import worker  # noqa: E402
from app.services.kotak_struk.extract import KIND_IMAGE, TextDoc  # noqa: E402
from app.services.kotak_struk.readers.base import ParseContext  # noqa: E402
from app.services.kotak_struk.registry import read_document  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "kotak"
DEFAULT_LINES = _FIXTURES / "sweep_lines.json"
DEFAULT_SNAPSHOT = _FIXTURES / "sweep_snapshot.json"
TODAY = date(2026, 11, 1)   # tetap: hasil sapuan tidak boleh ikut kalender
SWITCHES = (("off", False), ("on", True))
FIELDS = ("reader", "doc_type", "issuer", "status", "checks", "total", "paid_date", "counterparty", "unread_proof",
          "lines", "merchant")
_LEVEL = {"warn": 0, "block": 1}


async def snapshot_entry(lines: list[str], *, proofs_enabled: bool, user_name: str | None) -> dict:
    """Satu daftar baris, satu posisi saklar: yang akan disimpan worker (jenis, status, cek, nominal, tanggal, pihak,
    jumlah baris rincian, merchant) dan apakah teksnya diperlakukan sebagai bukti bayar yang tak terbaca."""
    text = TextDoc(lines=list(lines), kind=KIND_IMAGE)
    res = await read_document(text, ParseContext(today=TODAY, user_name=user_name), proofs_enabled=proofs_enabled)
    out = worker._outcome(res, text)
    doc, columns = res.parsed.doc, out.columns
    checks: dict[str, str] = {}
    for c in res.checks:   # kode ganda: level terkuat
        if _LEVEL.get(c.level, -1) >= _LEVEL.get(checks.get(c.code), -1):
            checks[c.code] = c.level
    total = doc.amounts.total
    return {
        "reader": res.reader,
        "doc_type": doc.doc_type,
        "issuer": doc.issuer,
        "status": doc.status,
        "checks": dict(sorted(checks.items())),
        "total": int(total) if total is not None else None,
        "paid_date": columns["parsed_date"].isoformat() if columns["parsed_date"] else None,
        "counterparty": columns["document"]["counterparty"]["name"],
        "unread_proof": bool(out.unread_proof),
        "lines": len(columns["document"]["lines"]),
        "merchant": columns["merchant"],
    }


def load_lines(path_lines=DEFAULT_LINES) -> list[dict]:
    return json.loads(Path(path_lines).read_text(encoding="utf-8"))


async def build(path_lines=DEFAULT_LINES) -> dict:
    """`{id: {"off": entry, "on": entry}}` untuk setiap daftar di `path_lines`."""
    result = {}
    for item in load_lines(path_lines):
        result[item["id"]] = {
            name: await snapshot_entry(item["lines"], proofs_enabled=enabled, user_name=item.get("user_name"))
            for name, enabled in SWITCHES
        }
    return result


def diff(old: dict, new: dict) -> list[str]:
    """Beda per id/saklar/field (`id saklar field: lama -> baru`); id yang hilang atau baru disebut sendiri."""
    out = []
    for key in sorted(set(old) | set(new)):
        if key not in new:
            out.append(f"{key}: hilang dari sapuan")
            continue
        if key not in old:
            out.append(f"{key}: baru (belum ada di snapshot)")
            continue
        for switch, _ in SWITCHES:
            a, b = old[key].get(switch) or {}, new[key].get(switch) or {}
            for field in sorted(set(a) | set(b), key=lambda f: (FIELDS.index(f) if f in FIELDS else len(FIELDS), f)):
                if a.get(field) != b.get(field):
                    out.append(f"{key} {switch} {field}: {json.dumps(a.get(field), ensure_ascii=False)} -> "
                               f"{json.dumps(b.get(field), ensure_ascii=False)}")
    return out


def format_snapshot(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("perintah", choices=("cek", "tulis"))
    ap.add_argument("--lines", default=str(DEFAULT_LINES))
    ap.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    args = ap.parse_args(argv)
    new = asyncio.run(build(args.lines))
    if args.perintah == "tulis":
        Path(args.snapshot).write_text(format_snapshot(new), encoding="utf-8")
        print(f"snapshot ditulis: {len(new)} daftar x {len(SWITCHES)} saklar -> {args.snapshot}")
        return 0
    try:
        old = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"snapshot tidak bisa dibaca: {args.snapshot} ({e!r})", file=sys.stderr)
        return 2
    changes = diff(old, new)
    for line in changes:
        print(line)
    print(f"{len(new)} daftar, {len(changes)} beda")
    return 1 if changes else 0


if __name__ == "__main__":
    sys.exit(main())
