"""Penyedia data kartu inti (Plugin B1). Satu fungsi per `key` di `registry.py`.

Kartu inti dikirim dalam bentuk yang bisa digambar komponen Beranda sekarang tanpa memanggil
endpoint lain (B2): field bentuk deklaratif (`shape`, dan untuk KPI `value` + `unit`) ditambah
`sumber`, yaitu potongan respons endpoint lama dengan nama sumber sebagai kunci. `value` hanya
diisi bila angkanya sudah ada utuh di respons server; angka yang sekarang dijumlah di frontend
(mis. total Tabungan) dibiarkan `null` dan tetap dihitung frontend sampai dipindah ke layanan.
Tidak ada rumus di file ini (AGENTS.md "Plugin dan ruang" aturan 6).
"""
from __future__ import annotations

from typing import Awaitable, Callable

from app.services.dashboard.sources import Sumber

Provider = Callable[[Sumber, dict], Awaitable[dict]]
PROVIDERS: dict[str, Provider] = {}


def provider(key: str):
    def daftar(fn: Provider) -> Provider:
        PROVIDERS[key] = fn
        return fn
    return daftar


def _aktif(adv: dict | None) -> bool:
    """Sama dengan `advisorEnabled` di frontend: flag aktif dan bentuk metrik utuh."""
    return bool(adv and adv.get("enabled") and isinstance((adv.get("metrics") or {}).get("harian"), list))


def _advisor_kpi(adv: dict | None, kartu: str) -> dict | None:
    """Potongan muatan AI Advisor untuk satu kartu KPI: metrik tanpa deret harian + chip kartu itu."""
    if not _aktif(adv):
        return {"enabled": False} if adv is not None else None
    metrics = {k: v for k, v in adv["metrics"].items() if k != "harian"}
    return {
        "enabled": True, "generated_at": adv.get("generated_at"), "metrics": metrics,
        "kpi": (adv.get("kpi") or {}).get(kartu), "redam_chip": adv.get("redam_chip"),
    }


def _kpi(value, sumber: dict) -> dict:
    return {"shape": "kpi", "value": value, "unit": "rp", "sumber": sumber}


def _m(adv: dict | None) -> dict:
    return adv["metrics"] if _aktif(adv) else {}


@provider("core.kpi.jatah")
async def kpi_jatah(s: Sumber, _settings: dict) -> dict:
    adv, harian, prediksi = await s.advisor(), await s.harian(), await s.prediksi()
    # Belanja hari ini: dari metrik advisor bila aktif; UI lama menjumlahkan baris harian di frontend.
    value = _m(adv).get("belanja_hari_ini")
    return _kpi(value, {"advisor": _advisor_kpi(adv, "jatah"), "harian": harian, "prediksi": prediksi})


@provider("core.kpi.sisa_bebas")
async def kpi_sisa_bebas(s: Sumber, _settings: dict) -> dict:
    adv, ringkasan, prediksi = await s.advisor(), await s.ringkasan_amplop(), await s.prediksi()
    m = _m(adv)
    value = m.get("sisa_bebas_harian") if m.get("sisa_bebas_harian") is not None else m.get("sisa_bebas")
    return _kpi(value, {"advisor": _advisor_kpi(adv, "sisa_bebas"), "ringkasan_amplop": ringkasan,
                        "prediksi": prediksi})


@provider("core.kpi.terpakai")
async def kpi_terpakai(s: Sumber, _settings: dict) -> dict:
    adv, ringkasan, prediksi = await s.advisor(), await s.ringkasan_amplop(), await s.prediksi()
    return _kpi(_m(adv).get("terpakai"), {"advisor": _advisor_kpi(adv, "terpakai"),
                                          "ringkasan_amplop": ringkasan, "prediksi": prediksi})


@provider("core.kpi.income")
async def kpi_income(s: Sumber, _settings: dict) -> dict:
    adv, prediksi = await s.advisor(), await s.prediksi()
    value = _m(adv).get("pemasukan_rumah_tangga")
    if value is None and prediksi:
        value = prediksi.get("total_income")
    return _kpi(value, {"advisor": _advisor_kpi(adv, "income"), "prediksi": prediksi})


@provider("core.kpi.tagihan")
async def kpi_tagihan(s: Sumber, _settings: dict) -> dict:
    adv, tagihan = await s.advisor(), await s.tagihan()
    value = tagihan.get("amount_due") if tagihan else None
    return _kpi(value, {"advisor": _advisor_kpi(adv, "tagihan"), "tagihan": tagihan})


@provider("core.kpi.tabungan")
async def kpi_tabungan(s: Sumber, _settings: dict) -> dict:
    adv, ringkasan, target = await s.advisor(), await s.ringkasan_amplop(), await s.target()
    return _kpi(None, {"advisor": _advisor_kpi(adv, "tabungan"), "ringkasan_amplop": ringkasan,
                       "target": target})


@provider("core.cocokkan_saldo")
async def cocokkan_saldo(s: Sumber, _settings: dict) -> dict:
    return {"shape": "inti", "sumber": {"saldo_cek": await s.saldo_cek()}}


@provider("core.pengeluaran_harian")
async def pengeluaran_harian(s: Sumber, _settings: dict) -> dict:
    adv, harian, prediksi = await s.advisor(), await s.harian(), await s.prediksi()
    potong = None
    if adv is not None:
        potong = ({"enabled": True, "generated_at": adv.get("generated_at"),
                   "metrics": {"harian": adv["metrics"]["harian"]}, "grafik": adv.get("grafik")}
                  if _aktif(adv) else {"enabled": False})
    return {"shape": "series", "sumber": {"advisor": potong, "harian": harian, "prediksi": prediksi}}


@provider("core.advisor")
async def advisor(s: Sumber, _settings: dict) -> dict:
    adv = await s.advisor()
    sumber = {"advisor": adv}
    if adv is not None and not _aktif(adv):
        # UI lama (kartu Perlu perhatian) selama flag advisor_v2_users belum mencakup user ini.
        sumber.update({
            "insights": await s.insights(), "ringkasan_amplop": await s.ringkasan_amplop(),
            "langganan": await s.langganan(), "pemasukan": await s.pemasukan(),
            "prediksi": await s.prediksi(),
        })
    return {"shape": "inti", "sumber": sumber}


@provider("core.ke_mana_uangmu")
async def ke_mana_uangmu(s: Sumber, _settings: dict) -> dict:
    return {"shape": "inti", "sumber": {"rincian": await s.rincian()}}


@provider("core.amplop_pengeluaran")
async def amplop_pengeluaran(s: Sumber, _settings: dict) -> dict:
    return {"shape": "inti", "sumber": {"ringkasan_amplop": await s.ringkasan_amplop()}}


@provider("core.target_tabungan")
async def target_tabungan(s: Sumber, _settings: dict) -> dict:
    return {"shape": "progress", "sumber": {"ringkasan_amplop": await s.ringkasan_amplop(),
                                            "target": await s.target()}}


@provider("core.transaksi_terbaru")
async def transaksi_terbaru(s: Sumber, settings: dict) -> dict:
    return {"shape": "list", "sumber": {"transaksi": await s.transaksi(settings["limit"]),
                                        "ringkasan_amplop": await s.ringkasan_amplop()}}


@provider("core.langganan")
async def langganan(s: Sumber, _settings: dict) -> dict:
    return {"shape": "list", "sumber": {"langganan": await s.langganan()}}


@provider("core.papan_disiplin")
async def papan_disiplin(s: Sumber, _settings: dict) -> dict:
    return {"shape": "list", "sumber": {"papan": await s.papan()}}
