"""Pemuat manifest plugin (Plugin H1).

`muat()` membaca setiap `app/plugins/<id>/manifest.json` (folder `host`, `sdk`, dan yang diawali `_`
dilewati), memvalidasi skemanya (`manifest.py`), lalu aturan antarplugin:

- nama folder = `id`, `id` unik;
- `requires` ada, tidak melingkar, dan mendukung semua jenis ruang plugin yang membutuhkannya;
- `conflicts` merujuk plugin yang ada;
- prefix callback bot, nama perintah bot, kode aturan advisor, dan kunci flag unik di seluruh plugin;
- (U1) setiap tabel di `entities` ada sebagai model dan memenuhi aturan tabel plugin (`host/data.py`).

Dua mode:
- **ketat** (validator CI, tes): galat apa pun = gagal. CI tidak pernah meloloskan manifest rusak.
- **start** (lifespan API): plugin yang tidak sah, beserta plugin yang membutuhkannya, **dilewati** dengan log
  galat. Satu manifest rusak tidak boleh menjatuhkan seluruh API; lagi pula CI sudah menolaknya lebih dulu.

Kode server (H2): folder plugin yang berisi `__init__.py` diperiksa impornya, diimpor, dan pendaftarannya
dicocokkan dengan manifest (`kode.py`). Galatnya diperlakukan sama dengan galat manifest di kedua mode.

Registry dimuat sekali per proses (`registry()`); tes mengganti isinya lewat `pakai_registry()`.
"""
import hashlib
import json
import logging
import pathlib
from contextlib import contextmanager
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.plugins.host.manifest import Manifest
from app.plugins.sdk.plugin import Plugin

log = logging.getLogger("jatahku.plugins")

FOLDER_PLUGIN = pathlib.Path(__file__).resolve().parents[1]
_BUKAN_PLUGIN = {"host", "sdk", "__pycache__"}


class ManifestTidakSah(Exception):
    def __init__(self, galat: list[str]):
        super().__init__("\n".join(galat))
        self.galat = galat


@dataclass
class Registry:
    plugins: dict[str, Manifest] = field(default_factory=dict)
    galat: list[str] = field(default_factory=list)
    kode: dict[str, Plugin] = field(default_factory=dict)      # H2: hanya plugin yang punya kode server

    def get(self, plugin_id: str) -> Manifest | None:
        return self.plugins.get(plugin_id)

    def kode_plugin(self, plugin_id: str) -> Plugin | None:
        return self.kode.get(plugin_id) if plugin_id in self.plugins else None

    def punya(self, jenis: str) -> bool:
        """Ada plugin dimuat yang mendaftarkan fungsi `jenis`? Titik ekstensi memakainya untuk melewati semua kerja
        (termasuk kueri DB) bila belum ada plugin yang menyumbang ke titik itu."""
        return any(p.semua(jenis) for pid, p in self.kode.items() if pid in self.plugins)

    def semua(self) -> list[Manifest]:
        return [self.plugins[k] for k in sorted(self.plugins)]

    def dibutuhkan_oleh(self, plugin_id: str) -> list[str]:
        return sorted(m.id for m in self.plugins.values() if plugin_id in m.requires)


def baca_folder(folder: pathlib.Path = FOLDER_PLUGIN) -> tuple[dict[str, Manifest], list[str]]:
    """Manifest yang skemanya sah per folder, dan galat skema."""
    hasil, galat = {}, []
    if not folder.is_dir():
        return hasil, galat
    for sub in sorted(folder.iterdir()):
        if not sub.is_dir() or sub.name in _BUKAN_PLUGIN or sub.name.startswith(("_", ".")):
            continue
        berkas = sub / "manifest.json"
        if not berkas.is_file():
            galat.append(f"{sub.name}: manifest.json tidak ada")
            continue
        try:
            m = Manifest.model_validate(json.loads(berkas.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            galat.append(f"{sub.name}: manifest.json bukan JSON sah ({e})")
            continue
        except ValidationError as e:
            for err in e.errors():
                lokasi = ".".join(str(x) for x in err["loc"]) or "manifest"
                galat.append(f"{sub.name}: {lokasi}: {err['msg']}")
            continue
        if m.id != sub.name:
            galat.append(f"{sub.name}: id '{m.id}' harus sama dengan nama folder")
            continue
        hasil[m.id] = m
    return hasil, galat


def periksa_antarplugin(plugins: dict[str, Manifest]) -> dict[str, list[str]]:
    """Galat antarplugin per id plugin (plugin yang salah, bukan pasangannya)."""
    galat: dict[str, list[str]] = {}

    def salah(pid, pesan):
        galat.setdefault(pid, []).append(pesan)

    for m in plugins.values():
        for r in m.requires:
            dep = plugins.get(r)
            if dep is None:
                salah(m.id, f"requires '{r}' tidak ada")
            elif not set(m.space_types) <= set(dep.space_types):
                salah(m.id, f"requires '{r}' tidak mendukung semua jenis ruang {m.space_types}")
        for c in m.conflicts:
            if c not in plugins:
                salah(m.id, f"conflicts '{c}' tidak ada")

    # Lingkaran requires.
    def melingkar(pid, jalur):
        for r in plugins[pid].requires:
            if r == jalur[0]:
                return True
            if r in plugins and r not in jalur and melingkar(r, jalur + [r]):
                return True
        return False

    for pid in plugins:
        if melingkar(pid, [pid]):
            salah(pid, "requires melingkar")

    def unik(nama, ambil):
        pemilik: dict[str, str] = {}
        for m in sorted(plugins.values(), key=lambda x: x.id):
            for nilai in ambil(m):
                if nilai in pemilik and pemilik[nilai] != m.id:
                    salah(m.id, f"{nama} '{nilai}' sudah dipakai plugin '{pemilik[nilai]}'")
                pemilik.setdefault(nilai, m.id)

    unik("prefix callback", lambda m: [c.prefix for c in m.contributes.bot_callbacks])
    unik("perintah bot", lambda m: [c.command for c in m.contributes.bot_commands])
    unik("aturan advisor", lambda m: m.contributes.advisor_rules)
    unik("flag", lambda m: [m.flag_key])
    return galat


def _nama_modul(folder: pathlib.Path, plugin_id: str) -> str | None:
    """Folder repo → `app.plugins.<id>`; folder lain (tes) → nama modul unik per folder."""
    if folder.resolve() == FOLDER_PLUGIN:
        return None
    jejak = hashlib.sha1(str(folder.resolve()).encode()).hexdigest()[:10]
    return f"_jatahku_plugin_{jejak}_{plugin_id}"


def muat_semua_kode(folder: pathlib.Path, plugins: dict[str, Manifest]) -> tuple[dict[str, Plugin], dict[str, list]]:
    """Kode server tiap plugin yang punya `__init__.py`: (kode sah, galat per plugin)."""
    from app.plugins.host import kode as kode_mod
    hasil: dict[str, Plugin] = {}
    galat: dict[str, list[str]] = {}
    for pid, m in sorted(plugins.items()):
        sub = folder / pid
        if not (sub / "__init__.py").is_file():
            continue
        salah = kode_mod.periksa_impor(sub, m)
        if salah:
            galat[pid] = salah
            continue
        try:
            p = kode_mod.muat_kode(sub, pid, nama_modul=_nama_modul(folder, pid))
        except Exception as e:      # galat saat impor tidak boleh menjatuhkan API (mode start)
            galat[pid] = [f"kode gagal dimuat: {type(e).__name__}: {e}"]
            continue
        salah = kode_mod.cocokkan(m, p)
        if salah:
            galat[pid] = salah
            continue
        hasil[pid] = p
    return hasil, galat


def periksa_entitas(plugins: dict[str, Manifest]) -> dict[str, list[str]]:
    """U1: setiap `entities` manifest ada sebagai model dan memenuhi aturan tabel plugin (`host/data.py`)."""
    from app.plugins.host import data
    galat = {}
    for pid, m in plugins.items():
        salah = data.periksa_entitas(m)
        if salah:
            galat[pid] = salah
    return galat


def muat(folder: pathlib.Path = FOLDER_PLUGIN, *, ketat: bool = False) -> Registry:
    plugins, galat = baca_folder(folder)
    antar = periksa_antarplugin(plugins)
    for pid, daftar in periksa_entitas(plugins).items():
        antar.setdefault(pid, []).extend(daftar)
    for pid, daftar in sorted(antar.items()):
        galat.extend(f"{pid}: {p}" for p in daftar)
    # Kode hanya dimuat untuk plugin yang lolos aturan antarplugin.
    kode, galat_kode = muat_semua_kode(folder, {k: v for k, v in plugins.items() if k not in antar})
    for pid, daftar in sorted(galat_kode.items()):
        galat.extend(f"{pid}: {p}" for p in daftar)
    if ketat:
        if galat:
            raise ManifestTidakSah(galat)
        return Registry(plugins=plugins, kode=kode)

    # Mode start: buang yang salah, lalu yang (berantai) membutuhkan plugin terbuang.
    sah = {k: v for k, v in plugins.items() if k not in antar and k not in galat_kode}
    while True:
        buang = [k for k, v in sah.items() if any(r not in sah for r in v.requires)]
        if not buang:
            break
        for k in buang:
            galat.append(f"{k}: dilewati karena plugin yang dibutuhkan tidak dimuat")
            del sah[k]
    for g in galat:
        log.error("plugin tidak dimuat: %s", g)
    return Registry(plugins=sah, galat=galat, kode={k: v for k, v in kode.items() if k in sah})


_REGISTRY: Registry | None = None


def registry() -> Registry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = muat()
    return _REGISTRY


def muat_saat_start() -> Registry:
    """Dipanggil lifespan API. Memuat ulang dari disk (deploy = restart = manifest baru)."""
    global _REGISTRY
    _REGISTRY = muat()
    # print, seperti baris start lain di main.py: logging tidak dikonfigurasi, INFO tidak sampai ke journal.
    # Galat per plugin tetap lewat log.error (WARNING ke atas selalu tercetak).
    print(f"🧩 plugin dimuat: {', '.join(_REGISTRY.plugins) or '(tidak ada)'}")
    return _REGISTRY


@contextmanager
def pakai_registry(reg: Registry):
    """Tes: ganti registry sementara."""
    global _REGISTRY
    lama, _REGISTRY = _REGISTRY, reg
    try:
        yield reg
    finally:
        _REGISTRY = lama
