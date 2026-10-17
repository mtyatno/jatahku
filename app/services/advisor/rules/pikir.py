"""Aturan I. Pikir-Pikir — PP-01..03 (02-aturan.md §6I). Fungsi murni `(Konteks) → [Insight]`.

Pikir-Pikir Fase 2 (refleksi "Sepadan?") dan Fase 3 (Incaran) belum ada di `main`, jadi
belum ada tabel, loader, atau endpoint. Modul ini menetapkan bentuk masukan yang dibutuhkan
aturan (`RefleksiSnap`, `IncaranSnap`) dan membacanya dari `snap.refleksi` / `snap.incaran`
lewat `getattr` — Snapshot hari ini tidak punya field itu, jadi aturan diam (tidak menyala).
Sesi yang membangun Pikir-Pikir Fase 2/3 cukup: menambah kedua field di `snapshot.Snapshot`
+ loader-nya, mendaftarkan `pikir.evaluasi` di `dashboard.EVALUATOR`, dan membuat penerima
aksi `pikir` di frontend (04-kontrak-api.md).

Keputusan kecil S19 (juga di SESI-LOG.md):
- PP-01 satu insight untuk semua refleksi jatuh tempo (bukan satu per transaksi), supaya
  daftar tidak penuh refleksi. Entitas = refleksi tertua; CTA "Jawab" membuka yang tertua.
- PP-02 satu insight per Incaran yang `think_until`-nya lewat (tiap Incaran keputusan sendiri).
  "Beli" = `expense` terisi (deskripsi, jumlah, amplop); "Nggak jadi" / "Tunda" = aksi `pikir`.
- PP-03 menghitung jawaban "menyesal" menurut tanggal transaksinya, dalam periode berjalan +
  periode sebelumnya. Satu insight per amplop.
- Semua PP tone info, tanpa CTA pemindah dana; urgensi PP-02 > PP-01 > PP-03.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.services.advisor.insight import Insight, Konteks

JAWABAN = ("sepadan", "menyesal")


@dataclass(frozen=True)
class RefleksiSnap:
    """Refleksi "Sepadan?" untuk satu transaksi (Pikir-Pikir Fase 2)."""
    id: str
    txn_id: str
    envelope_id: str | None
    deskripsi: str
    jumlah: Decimal
    tanggal_txn: date
    jatuh_tempo: date              # kapan pertanyaan "Sepadan?" boleh diajukan
    jawaban: str | None = None     # None | "sepadan" | "menyesal"


@dataclass(frozen=True)
class IncaranSnap:
    """Barang yang sedang dipikir-pikir (Pikir-Pikir Fase 3)."""
    id: str
    nama: str
    jumlah: Decimal
    envelope_id: str | None
    think_until: datetime          # aware; keputusan dibuka saat now ≥ think_until
    status: str = "menunggu"       # menunggu | dibeli | batal


def _refleksi(ctx: Konteks) -> list[RefleksiSnap]:
    return list(getattr(ctx.snap, "refleksi", None) or [])


def _incaran(ctx: Konteks) -> list[IncaranSnap]:
    return list(getattr(ctx.snap, "incaran", None) or [])


def pp_01(ctx: Konteks) -> list[Insight]:
    today = ctx.m.today
    tempo = sorted((r for r in _refleksi(ctx) if r.jawaban is None and r.jatuh_tempo <= today),
                   key=lambda r: (r.jatuh_tempo, r.id))
    if not tempo:
        return []
    r = tempo[0]
    return [Insight(
        aturan="PP-01", entitas=r.id, tone="info", slot=("daftar",),
        data={"n": len(tempo), "deskripsi": r.deskripsi, "jumlah": r.jumlah, "tanggal": r.tanggal_txn,
              "amplop": ctx.nama.get(r.envelope_id, "") if r.envelope_id else ""},
        aksi=[{"kind": "pikir", "kode": "jawab_refleksi", "payload": {"refleksi_id": r.id}}],
        rupiah=sum((x.jumlah for x in tempo), Decimal("0")), urgensi=Decimal("0.3"),
        amplop_id=r.envelope_id,
    )]


def pp_02(ctx: Konteks) -> list[Insight]:
    now = getattr(ctx.snap, "now", None)
    if now is None:
        return []
    out = []
    for x in sorted(_incaran(ctx), key=lambda x: (x.think_until, x.id)):
        if x.status != "menunggu" or now < x.think_until:
            continue
        out.append(Insight(
            aturan="PP-02", entitas=x.id, tone="info", slot=("daftar",),
            data={"nama": x.nama, "jumlah": x.jumlah, "sejak": x.think_until,
                  "amplop": ctx.nama.get(x.envelope_id, "") if x.envelope_id else ""},
            aksi=[{"kind": "expense", "kode": "beli_incaran",
                   "payload": {"deskripsi": x.nama, "jumlah": x.jumlah, "amplop_id": x.envelope_id,
                               "incaran_id": x.id}},
                  {"kind": "pikir", "kode": "nggak_jadi", "payload": {"incaran_id": x.id}},
                  {"kind": "pikir", "kode": "tunda_incaran", "payload": {"incaran_id": x.id}}],
            rupiah=x.jumlah, urgensi=Decimal("0.5"), amplop_id=x.envelope_id,
        ))
    return out


def pp_03(ctx: Konteks) -> list[Insight]:
    periods = ctx.snap.periods
    if not periods:
        return []
    mulai = periods[-2][0] if len(periods) >= 2 else periods[-1][0]
    per_amplop: dict[str, list[RefleksiSnap]] = {}
    for r in _refleksi(ctx):
        if r.jawaban == "menyesal" and r.envelope_id and mulai <= r.tanggal_txn <= ctx.m.today:
            per_amplop.setdefault(r.envelope_id, []).append(r)
    out = []
    for eid, xs in sorted(per_amplop.items()):
        if len(xs) < ctx.k.pola_menyesal_n:
            continue
        out.append(Insight(
            aturan="PP-03", entitas=eid, tone="info", slot=("daftar", "amplop"),
            data={"amplop_id": eid, "amplop": ctx.nama.get(eid, ""), "n": len(xs),
                  "total": sum((x.jumlah for x in xs), Decimal("0"))},
            aksi=[{"kind": "pikir", "kode": "pakai_incaran", "payload": {"amplop_id": eid}}],
            rupiah=sum((x.jumlah for x in xs), Decimal("0")), urgensi=Decimal("0.2"), amplop_id=eid,
        ))
    return out


def evaluasi(ctx: Konteks) -> list[Insight]:
    return [*pp_01(ctx), *pp_02(ctx), *pp_03(ctx)]
