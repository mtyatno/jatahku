"""Isi `GET /app/config` (ADR-M9, ADR-M10, paket mobile 1.3).

Satu tempat untuk hal yang harus bisa diubah server tanpa rilis toko:
versi minimum/terbaru per platform, mode jualan per platform, flag fitur,
tautan legal, dan slot bundle OTA.

Nilai bawaan di kode = perilaku web hari ini. Pemilik produk bisa menimpanya
tanpa deploy lewat AppSetting `app_config` (JSON), mis. untuk menaikkan versi
minimum Android saat darurat:

    {"platforms": {"android": {"min_supported_version": "1.1.0"}},
     "features": {"receipt_inbox": {"web": true}}}

Bentuk respons adalah kontrak dengan aplikasi terpasang: field hanya boleh
ditambah, tidak dihapus atau diubah artinya (AGENTS.md, aturan mobile #2).
"""
from __future__ import annotations

import copy
import json
import logging

from app.core.client import ClientInfo, PLATFORMS, is_older

log = logging.getLogger(__name__)

CONFIG_VERSION = 1
SETTING_KEY = "app_config"

# none  = tanpa teks/tautan beli (teks kuota netral)
# store = tombol beli memanggil billing toko (paket 5.5)
# web   = alur bayar web yang ada sekarang
SALES_MODES = ("none", "store", "web")

# Fitur yang belum siap disembunyikan di sini sampai paketnya selesai
# (03-workflow.md §2). Kunci baru ditambah oleh paket pemiliknya.
FEATURES: dict[str, bool] = {
    "receipt_inbox": False,  # Kotak Struk (FS.8)
    "push": False,           # push native (3.5)
    "biometric_lock": False, # kunci biometrik (3.6)
}

DEFAULTS: dict = {
    "platforms": {
        "web": {
            "min_supported_version": None,  # web diperbarui service worker, tidak pernah dikunci
            "latest_version": None,
            "store_url": None,
            "sales_mode": "web",
            "ota": None,
        },
        "android": {
            "min_supported_version": None,
            "latest_version": None,
            "store_url": "https://play.google.com/store/apps/details?id=com.jatahku.app",
            "sales_mode": "none",
            "ota": None,
        },
        "ios": {
            "min_supported_version": None,
            "latest_version": None,
            "store_url": None,  # diisi setelah App Store Connect (5.7)
            "sales_mode": "none",
            "ota": None,
        },
    },
    "features": {},  # {nama: bool | {platform: bool}} — menimpa FEATURES
    "links": {
        "privacy": "https://jatahku.com/privacy.html",
        "terms": "https://jatahku.com/terms.html",
        "account_deletion": None,  # halaman permintaan hapus akun (1.2)
        "support": None,
    },
    "error_reporting": {"enabled": True, "sample_rate": 1.0},
}


def parse_overrides(raw: str | None) -> dict:
    """Isi AppSetting → dict. Rusak/kosong → {} (config tetap jalan dengan bawaan)."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        log.warning("AppSetting %s bukan JSON yang sah; memakai bawaan", SETTING_KEY)
        return {}
    return data if isinstance(data, dict) else {}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _features_for(platform: str, overrides: dict) -> dict[str, bool]:
    out = dict(FEATURES)
    for name, value in (overrides or {}).items():
        if isinstance(value, bool):
            out[name] = value
        elif isinstance(value, dict) and isinstance(value.get(platform), bool):
            out[name] = value[platform]
    return out


def _update_status(client: ClientInfo, plat: dict) -> str:
    if is_older(client.version, plat.get("min_supported_version")):
        return "required"
    if is_older(client.version, plat.get("latest_version")):
        return "recommended"
    return "ok"


def build_config(client: ClientInfo, overrides: dict | None = None) -> dict:
    cfg = _merge(DEFAULTS, overrides or {})
    # Klien tanpa header (web lama, skrip) diperlakukan seperti web hari ini.
    platform = client.platform if client.platform in PLATFORMS else "web"
    plat = cfg["platforms"].get(platform) or {}
    sales_mode = plat.get("sales_mode")
    if sales_mode not in SALES_MODES:
        sales_mode = DEFAULTS["platforms"][platform]["sales_mode"]

    versions = {
        p: {
            "min_supported": (cfg["platforms"].get(p) or {}).get("min_supported_version"),
            "latest": (cfg["platforms"].get(p) or {}).get("latest_version"),
            "store_url": (cfg["platforms"].get(p) or {}).get("store_url"),
        }
        for p in PLATFORMS
    }
    ota = plat.get("ota") if isinstance(plat.get("ota"), dict) else {}

    return {
        "config_version": CONFIG_VERSION,
        "client": {
            "platform": client.platform,
            "version": client.version,
            "build": client.build,
        },
        "update": {
            "status": _update_status(client, plat),  # ok | recommended | required
            "min_supported_version": plat.get("min_supported_version"),
            "latest_version": plat.get("latest_version"),
            "store_url": plat.get("store_url"),
        },
        "versions": versions,
        "sales_mode": sales_mode,
        "features": _features_for(platform, cfg.get("features") or {}),
        "links": cfg["links"],
        "ota": {
            "channel": ota.get("channel"),
            "bundle_url": ota.get("bundle_url"),
            "bundle_version": ota.get("bundle_version"),
            "min_native_version": ota.get("min_native_version"),
        },
        "error_reporting": cfg["error_reporting"],
    }
