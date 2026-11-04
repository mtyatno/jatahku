"""Kode server plugin: pemeriksaan impor, pemuatan, dan pencocokan dengan manifest (Plugin H2).

Dipanggil `registry.muat()` untuk setiap plugin yang manifestnya sah dan foldernya berisi `__init__.py`.
Urutannya: impor diperiksa statis (AST) **sebelum** kode dijalankan, baru paket diimpor, lalu pendaftarannya
dicocokkan dengan manifest. Plugin tanpa `__init__.py` hanya manifest: kontribusi servernya tidak berbuat apa-apa.

Aturan impor (AGENTS.md "Plugin dan ruang" aturan 4): kode plugin hanya boleh mengimpor pustaka, nama publik
`app.plugins.sdk` (`from app.plugins.sdk import X` dengan X di `__all__`; bukan submodulnya), paketnya sendiri, dan
paket plugin di `requires`. Model, route, service, bot, `app.core`, dan host plugin tidak boleh. Begitu juga jalan
pintas yang lazim untuk melewati aturan ini (review keamanan PR #186 temuan 4): impor dinamis dan introspeksi
(`importlib`, `sys`, `gc`, `inspect`, `ctypes`, `builtins`, `__import__`, `eval`, `exec`, `compile`, `globals`,
`locals`, `vars`), `getattr`/`setattr`/`delattr` dengan nama yang bukan teks tetap atau berawalan `_`, dan atribut
dunder seperti `__globals__`, `__dict__`, `__class__`. Pemeriksaan ini menjaga disiplin plugin T1 (kode sendiri yang
direview), bukan sandbox; keadaan `PluginContext` sendiri ada di host (`keadaan.py`).

Izin per jenis fungsi (`IZIN_PER_JENIS`, review #186 temuan 1): kartu, cek, aturan advisor, perintah bot, dan field
form hanya membaca; mengirim notifikasi hanya dari job (konteks tanpa user, yang hanya melihat data bersama). Izin
tulis belum dibuka untuk titik mana pun (U2). Dicek di sini saat memuat dan lagi saat berjalan (`titik.izin_efektif`).
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import pathlib
import sys

from app.plugins.host.manifest import Manifest
from app.plugins.sdk.plugin import JENIS, Plugin

TERLARANG = ("app.models", "app.api", "app.services", "app.bot", "app.core", "app.main", "app.plugins.host",
             "app.schemas", "app.scripts", "app.tests")
MODUL_TERLARANG = ("importlib", "sys", "gc", "inspect", "ctypes", "builtins")
PANGGILAN_TERLARANG = ("__import__", "eval", "exec", "compile", "globals", "locals", "vars")
PANGGILAN_NAMA = ("getattr", "setattr", "delattr", "hasattr")
DUNDER_BOLEH = {"__name__", "__doc__", "__init__", "__post_init__"}
ATRIBUT_TERLARANG = {"_db"}

IZIN_BACA = frozenset({"envelopes:read", "transactions:read", "incomes:read", "members:read", "files:read"})
IZIN_PER_JENIS: dict[str, frozenset[str]] = {
    "kartu": IZIN_BACA,
    "cek": IZIN_BACA,
    "aturan_advisor": IZIN_BACA,
    "perintah_bot": IZIN_BACA,          # ADR-P2: chat tidak pernah menulis
    "field_form": IZIN_BACA,
    "job": IZIN_BACA | {"notifications:send"},
}


def _nama_publik_sdk() -> set[str]:
    from app.plugins import sdk
    return set(sdk.__all__)


def _modul_absolut(node: ast.ImportFrom, paket: str, berkas: pathlib.Path, akar: pathlib.Path) -> str | None:
    """Nama modul absolut untuk `from ... import`; relatif diselesaikan terhadap paket plugin."""
    if node.level == 0:
        return node.module
    bagian = berkas.relative_to(akar).with_suffix("").parts[:-1]   # folder di dalam plugin
    naik = node.level - 1
    if naik > len(bagian):
        return "app.plugins"          # keluar dari paket plugin
    dasar = [paket, *bagian[:len(bagian) - naik]]
    return ".".join(dasar + ([node.module] if node.module else []))


def periksa_impor(folder: pathlib.Path, m: Manifest) -> list[str]:
    """Galat impor dan jalan pintas di semua berkas .py plugin (tanpa menjalankannya)."""
    paket = f"app.plugins.{m.id}"
    boleh_plugin = {f"app.plugins.{m.id}", *(f"app.plugins.{r}" for r in m.requires)}
    publik = _nama_publik_sdk()
    galat = []

    def nilai(nama: str, berkas, baris, *, dari: bool = False, nama_impor=()):
        if nama.split(".")[0] in MODUL_TERLARANG:
            galat.append(f"{berkas}:{baris}: impor '{nama}' tidak boleh (impor dinamis/introspeksi)")
            return
        if nama == "app" or nama == "app.plugins":
            galat.append(f"{berkas}:{baris}: impor '{nama}' terlalu luas; pakai app.plugins.sdk")
            return
        if any(nama == t or nama.startswith(t + ".") for t in TERLARANG):
            galat.append(f"{berkas}:{baris}: impor '{nama}' tidak boleh; pakai app.plugins.sdk (aturan 4)")
            return
        if nama == "app.plugins.sdk" or nama.startswith("app.plugins.sdk."):
            if not dari or nama != "app.plugins.sdk":
                galat.append(f"{berkas}:{baris}: impor '{nama}' tidak boleh; pakai `from app.plugins.sdk import …`")
                return
            for n in nama_impor:
                if n not in publik:
                    galat.append(f"{berkas}:{baris}: '{n}' bukan nama publik app.plugins.sdk")
            return
        if nama.startswith("app.plugins.") and not any(nama == b or nama.startswith(b + ".") for b in boleh_plugin):
            galat.append(f"{berkas}:{baris}: impor '{nama}' dari plugin di luar requires")
            return
        if nama.startswith("app.") and not nama.startswith("app.plugins."):
            galat.append(f"{berkas}:{baris}: impor '{nama}' tidak boleh; pakai app.plugins.sdk (aturan 4)")

    for berkas in sorted(folder.rglob("*.py")):
        rel = berkas.relative_to(folder)
        if any(p.startswith(".") or p == "__pycache__" for p in rel.parts):
            continue
        try:
            pohon = ast.parse(berkas.read_text(encoding="utf-8"), filename=str(berkas))
        except SyntaxError as e:
            galat.append(f"{rel}: kode tidak bisa dibaca ({e.msg}, baris {e.lineno})")
            continue
        for node in ast.walk(pohon):
            if isinstance(node, ast.Import):
                for a in node.names:
                    nilai(a.name, rel, node.lineno)
            elif isinstance(node, ast.ImportFrom):
                mod = _modul_absolut(node, paket, berkas, folder)
                if mod is not None:          # `from app import models` → "app" (terlalu luas, ditolak)
                    nilai(mod, rel, node.lineno, dari=True, nama_impor=[a.name for a in node.names])
            elif isinstance(node, ast.Attribute):
                a = node.attr
                if a in ATRIBUT_TERLARANG or (a.startswith("__") and a.endswith("__") and a not in DUNDER_BOLEH):
                    galat.append(f"{rel}:{node.lineno}: atribut '.{a}' tidak boleh; data inti hanya lewat PluginContext")
            elif isinstance(node, ast.Call):
                f = node.func
                nama = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                if nama in PANGGILAN_TERLARANG:
                    galat.append(f"{rel}:{node.lineno}: {nama}() tidak boleh")
                elif isinstance(f, ast.Name) and nama in PANGGILAN_NAMA:
                    arg = node.args[1] if len(node.args) > 1 else None
                    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                            and not arg.value.startswith("_")):
                        galat.append(f"{rel}:{node.lineno}: {nama}() hanya dengan nama atribut tetap tanpa '_'")
    return galat


def muat_kode(folder: pathlib.Path, plugin_id: str, *, nama_modul: str | None = None) -> Plugin:
    """Impor paket plugin dan ambil atribut `plugin`. `nama_modul` None = `app.plugins.<id>` (folder repo)."""
    if nama_modul is None:
        modul = importlib.import_module(f"app.plugins.{plugin_id}")
    else:
        if nama_modul in sys.modules:
            modul = sys.modules[nama_modul]
        else:
            spec = importlib.util.spec_from_file_location(nama_modul, folder / "__init__.py",
                                                          submodule_search_locations=[str(folder)])
            modul = importlib.util.module_from_spec(spec)
            sys.modules[nama_modul] = modul
            try:
                spec.loader.exec_module(modul)
            except BaseException:
                sys.modules.pop(nama_modul, None)
                raise
    p = getattr(modul, "plugin", None)
    if not isinstance(p, Plugin):
        raise TypeError("__init__.py harus membuat `plugin = Plugin(\"<id>\")` dari app.plugins.sdk")
    return p


def _kontribusi(m: Manifest) -> dict[str, set[str]]:
    c = m.contributes
    return {
        "kartu": {k.key for k in c.cards},
        "cek": set(c.checks),
        "aturan_advisor": set(c.advisor_rules),
        "perintah_bot": {b.command for b in c.bot_commands},
        "job": {j.key for j in c.jobs},
        "field_form": {f"{f.target}.{f.key}" for f in c.form_fields},
    }


def cocokkan(m: Manifest, p: Plugin) -> list[str]:
    """Pendaftaran kode ↔ manifest: tidak ada fungsi tanpa manifest, tidak ada kontribusi tanpa fungsi,
    dan izin fungsi bagian dari izin manifest."""
    galat = []
    if p.id != m.id:
        galat.append(f"Plugin('{p.id}') harus Plugin('{m.id}')")
    harus = _kontribusi(m)
    izin_manifest = set(m.permissions)
    for jenis in JENIS:
        ada = {d.kunci for d in p.semua(jenis)}
        for k in sorted(ada - harus[jenis]):
            galat.append(f"{jenis} '{k}' didaftarkan di kode tetapi tidak ada di manifest ({JENIS[jenis]})")
        for k in sorted(harus[jenis] - ada):
            galat.append(f"{JENIS[jenis]} '{k}' di manifest tidak punya fungsi (@plugin.{jenis})")
    for d in p.semua():
        lebih = set(d.izin) - izin_manifest
        if lebih:
            galat.append(f"{d.jenis} '{d.kunci}' meminta izin di luar manifest: {', '.join(sorted(lebih))}")
        jenis_salah = set(d.izin) - IZIN_PER_JENIS.get(d.jenis, frozenset())
        if jenis_salah:
            galat.append(f"{d.jenis} '{d.kunci}' meminta izin yang tidak boleh untuk {d.jenis}: "
                         f"{', '.join(sorted(jenis_salah))} (hanya baca; kirim hanya dari job)")
    return galat
