"""Skema manifest plugin (Plugin H1; docs/plugin/01-kajian.md "Manifest dan titik ekstensi").

Setiap plugin membawa `app/plugins/<id>/manifest.json`. Host hanya mengenal plugin lewat manifest:
tidak ada kartu, menu, perintah, atau job yang muncul tanpa tercantum di sini.

Aturan T1 yang ditegakkan di sini (bukan hanya di dokumen):
- penerbit hanya "Jatahku" (ADR-P9: plugin buatan sendiri yang ikut rilis);
- izin hanya dari `IZIN`; `ai:analyze` dan `network:*` ditolak (ADR-P14, data tidak keluar);
- cakupan hanya `ruang` (cakupan pribadi diputuskan saat ada plugin pertamanya, ADR-P11);
- tabel plugin berawalan `p_<id>_` (AGENTS.md aturan 5); kunci kartu, aksi, dan notifikasi berawalan `<id>.`;
  kode aturan advisor (mis. `BU-01`) unik di seluruh registry;
- perintah bot hanya `kind: read` dan wajib menyatakan `audience` (ADR-P2, P3);
- copot selalu arsip 90 hari (ADR-P15); aksi cepat maksimal 2.

Aturan antarplugin (id unik, `requires`, `conflicts`, prefix callback) ada di `registry.py`.
"""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Versi Plugin API yang disediakan host. Satu versi mayor hanya bertambah (01-kajian.md, "Versi dan kompatibilitas").
PLUGIN_API_VERSION = (1, 0, 0)

PENERBIT_T1 = "Jatahku"
JENIS_RUANG = ("rumah_tangga", "usaha")
CARD_SIZES = ("S", "M", "L", "XL")             # = app/services/dashboard/registry.py SIZES
CARD_SHAPES = ("kpi", "progress", "list", "table", "series", "alert")  # registry SHAPES tanpa "inti"
ID_DICADANGKAN = {"host", "sdk", "core", "inti", "plugin", "plugins"}

# Daftar izin dan teks di layar izin (01-kajian.md, "Daftar izin"). Menambah izin = PR yang menyentuh file ini
# dan `PluginContext` (H2) sekaligus.
IZIN: dict[str, str] = {
    "envelopes:read": "Melihat amplop dan saldonya",
    "envelopes:write": "Membuat dan mengubah amplop",
    "transactions:read": "Melihat transaksi",
    "transactions:write": "Mencatat transaksi atas namamu",
    "incomes:read": "Melihat pemasukan",
    "incomes:write": "Mencatat pemasukan",
    "funds:move": "Mengusulkan pemindahan dana (kamu yang menyetujui)",
    "members:read": "Melihat anggota ruang",
    "notifications:send": "Mengirim pengingat",
    "files:read": "Membaca lampiran",
    "files:write": "Menyimpan lampiran",
    "reports:create": "Membuat laporan",
}
IZIN_TERLARANG_T1 = ("ai:analyze", "network:")   # ADR-P14; network:<domain> butuh ADR baru

# Perintah dan pola callback bot inti (`app/bot/handlers.py` `bot_commands()`/`bot_callbacks()`). Disalin sebagai
# konstanta supaya validator tidak mengimpor bot; `test_plugin_host` gagal bila keduanya berbeda. Plugin tidak boleh
# menimpa perintah inti atau memakai prefix callback yang ditangkap pola inti (mis. `lock_` = aksi tulis kunci amplop).
PERINTAH_INTI = frozenset({
    "amplop", "amplop_baru", "batal", "controls", "hapus_langganan", "help", "invite", "join", "langganan", "link",
    "lock", "pending", "setcooling", "setlimit", "start", "status", "tagihan", "tambah_langganan", "tanya", "target",
    "template", "unlink", "webapp",
})
POLA_CALLBACK_INTI = (
    r"^lock_", r"^delrec_", r"^recpay_", r"^recskip_", r"^recstop_", r"^addsub_", r"^merge_", r"^unlink_", r"^cool_",
    r"^checkin_", r"^tpl_", r"^k[nxdo]_", r"^kt_", r"^t_", r"^ky_", r"^batch_", r"^bshift_", r"^blimit_", r"^struk_",
    r"^intentlearn:", r"^dlimit:", r"^fshift:", r"^sim:", r"^tanya:",
)

_ID = re.compile(r"^[a-z][a-z0-9_]{1,29}$")
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_SYARAT = re.compile(r"^(>=|<=|>|<|==)\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?$")
_ROUTE = re.compile(r"^/p/[a-z][a-z0-9_]*(/[a-z0-9_\-]+)*$")
_PERINTAH = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_PREFIX_CB = re.compile(r"^[a-z][a-z0-9]{1,5}_$")


def _versi(teks: str) -> tuple[int, int, int]:
    m = _SEMVER.match(teks)
    if not m:
        raise ValueError(f"versi '{teks}' bukan semver (mis. 1.0.0)")
    return tuple(int(x) for x in m.groups())


def cocok_rentang(rentang: str, versi: tuple[int, int, int] = PLUGIN_API_VERSION) -> bool:
    """`">=1.0 <2.0"` → True bila `versi` memenuhi semua syarat. Galat bila rentang tidak terbaca."""
    syarat = rentang.split()
    if not syarat:
        raise ValueError("rentang plugin_api kosong")
    for s in syarat:
        m = _SYARAT.match(s)
        if not m:
            raise ValueError(f"syarat '{s}' tidak terbaca (pakai mis. '>=1.0 <2.0')")
        op = m.group(1)
        batas = tuple(int(x or 0) for x in m.group(2, 3, 4))
        ok = {">=": versi >= batas, "<=": versi <= batas, ">": versi > batas,
              "<": versi < batas, "==": versi == batas}[op]
        if not ok:
            return False
    return True


class _Ketat(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Engines(_Ketat):
    plugin_api: str

    @field_validator("plugin_api")
    @classmethod
    def _rentang(cls, v):
        if not cocok_rentang(v):
            raise ValueError(f"plugin_api '{v}' tidak cocok dengan host {'.'.join(map(str, PLUGIN_API_VERSION))}")
        return v


class Kartu(_Ketat):
    key: str
    title: str = Field(min_length=1, max_length=40)
    shape: Literal[CARD_SHAPES]
    sizes: list[Literal[CARD_SIZES]] = Field(min_length=1)
    default: bool = False          # ditawarkan masuk Beranda saat pasang


class Halaman(_Ketat):
    route: str
    title: str = Field(min_length=1, max_length=40)
    nav: Literal["usaha", "lainnya"] | None = None

    @field_validator("route")
    @classmethod
    def _route(cls, v):
        if not _ROUTE.match(v):
            raise ValueError(f"route '{v}' harus berawalan /p/<id>")
        return v


class AksiCepat(_Ketat):
    key: str
    label: str = Field(min_length=1, max_length=30)


class FieldForm(_Ketat):
    target: Literal["transaction", "income", "envelope"]
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    type: Literal["text", "number", "reference", "select"]
    label: str = Field(min_length=1, max_length=40)
    entity: str | None = None


class Job(_Ketat):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    schedule: str = Field(min_length=1, max_length=60)


class PerintahBot(_Ketat):
    command: str
    help: str = Field(min_length=1, max_length=60)
    kind: Literal["read"]                       # ADR-P2: tidak ada transaksi lewat chat
    audience: Literal["admin", "semua"]          # ADR-P3: data keuangan hanya admin

    @field_validator("command")
    @classmethod
    def _cmd(cls, v):
        if not _PERINTAH.match(v):
            raise ValueError(f"perintah '{v}' tidak sah")
        if v in PERINTAH_INTI:
            raise ValueError(f"perintah '/{v}' milik bot inti")
        return v


class CallbackBot(_Ketat):
    prefix: str

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, v):
        # Data callback Telegram maksimal 64 byte: prefix pendek, diakhiri garis bawah.
        if not _PREFIX_CB.match(v):
            raise ValueError(f"prefix callback '{v}' harus 2–6 huruf/angka diakhiri '_' (mis. 'bu_')")
        bentrok = [p for p in POLA_CALLBACK_INTI if re.match(p, v + "0")]
        if bentrok:
            raise ValueError(f"prefix callback '{v}' ditangkap pola bot inti {bentrok[0]}")
        return v


class Laporan(_Ketat):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    formats: list[Literal["pdf", "csv", "json"]] = Field(min_length=1)


class Kontribusi(_Ketat):
    cards: list[Kartu] = []
    pages: list[Halaman] = []
    quick_actions: list[AksiCepat] = Field(default=[], max_length=2)
    form_fields: list[FieldForm] = []
    events: list[str] = []
    jobs: list[Job] = []
    bot_commands: list[PerintahBot] = []
    bot_callbacks: list[CallbackBot] = []
    advisor_rules: list[str] = []
    notifications: list[str] = []
    reports: list[Laporan] = []
    settings_schema: dict | None = None
    setup: bool = False             # True = ada wizard; pasang → `installed` sampai `lanjut`


class Hak(_Ketat):
    sku: str = Field(pattern=r"^(plugin\.[a-z][a-z0-9_]*|bundle\.[a-z][a-z0-9_]*)$")
    trial_days: int = Field(default=0, ge=0, le=90)


class SiklusData(_Ketat):
    on_disable: Literal["read_only"] = "read_only"
    on_uninstall: Literal["archive_90_days"] = "archive_90_days"   # ADR-P15
    export: list[Literal["csv", "json"]] = []


class Manifest(_Ketat):
    id: str
    name: str = Field(min_length=1, max_length=40)
    version: str
    publisher: str
    description: str = Field(min_length=1, max_length=200)
    icon: str = Field(default="puzzle", max_length=30)
    category: str = Field(default="lainnya", max_length=30)
    engines: Engines
    requires: list[str] = []
    conflicts: list[str] = []
    space_types: list[Literal[JENIS_RUANG]] = Field(min_length=1)
    scope: Literal["ruang"] = "ruang"
    permissions: list[str] = []
    entities: list[str] = []
    contributes: Kontribusi = Kontribusi()
    entitlement: Hak | None = None
    data_lifecycle: SiklusData = SiklusData()
    flag: str | None = None          # AppSetting rollout; bawaan `plugin_<id>_users`

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not _ID.match(v) or v in ID_DICADANGKAN:
            raise ValueError(f"id '{v}' harus huruf kecil/angka/garis bawah, 2–30 karakter, bukan nama cadangan")
        return v

    @field_validator("flag")
    @classmethod
    def _flag(cls, v):
        # Hanya kunci rollout milik plugin: tidak boleh menumpang flag atau saklar inti (mis. ruang_usaha_users).
        if v is not None and not re.match(r"^plugin_[a-z0-9_]+_users$", v):
            raise ValueError(f"flag '{v}' harus berbentuk plugin_<nama>_users")
        return v

    @field_validator("version")
    @classmethod
    def _semver(cls, v):
        _versi(v)
        return v

    @field_validator("publisher")
    @classmethod
    def _t1(cls, v):
        if v != PENERBIT_T1:
            raise ValueError(f"penerbit harus '{PENERBIT_T1}': hanya plugin T1 selama 12 bulan (ADR-P9)")
        return v

    @field_validator("permissions")
    @classmethod
    def _izin(cls, v):
        for izin in v:
            if izin.startswith(IZIN_TERLARANG_T1):
                raise ValueError(f"izin '{izin}' dilarang di T1 (ADR-P14: data tidak keluar dari Jatahku)")
            if izin not in IZIN:
                raise ValueError(f"izin '{izin}' tidak dikenal (daftar di app/plugins/host/manifest.py IZIN)")
        if len(set(v)) != len(v):
            raise ValueError("izin ganda")
        return v

    @model_validator(mode="after")
    def _awalan(self):
        pid = self.id
        c = self.contributes
        for t in self.entities:
            if not t.startswith(f"p_{pid}_"):
                raise ValueError(f"tabel '{t}' harus berawalan p_{pid}_ (AGENTS.md aturan 5)")
        kunci = [k.key for k in c.cards] + [a.key for a in c.quick_actions]
        for k in kunci:
            if not k.startswith(f"{pid}."):
                raise ValueError(f"kunci '{k}' harus berawalan '{pid}.'")
        if len(set(kunci)) != len(kunci):
            raise ValueError("kunci kartu/aksi ganda")
        if len(set(c.advisor_rules)) != len(c.advisor_rules):
            raise ValueError("kode aturan advisor ganda")
        for h in c.pages:
            if not (h.route == f"/p/{pid}" or h.route.startswith(f"/p/{pid}/")):
                raise ValueError(f"route '{h.route}' harus di bawah /p/{pid}")
        for f in c.form_fields:
            if f.entity is not None and not f.entity.startswith(f"p_{pid}_") and \
                    not any(f.entity.startswith(f"p_{r}_") for r in self.requires):
                raise ValueError(f"field '{f.key}' merujuk tabel '{f.entity}' di luar plugin ini dan `requires`")
        for nama in c.notifications:
            if not nama.startswith(f"{pid}."):
                raise ValueError(f"notifikasi '{nama}' harus berawalan '{pid}.'")
        if pid in self.requires or pid in self.conflicts:
            raise ValueError("plugin tidak boleh membutuhkan atau bentrok dengan dirinya sendiri")
        if set(self.requires) & set(self.conflicts):
            raise ValueError("plugin yang sama ada di requires dan conflicts")
        return self

    @property
    def flag_key(self) -> str:
        return self.flag or f"plugin_{self.id}_users"

    def izin_tampil(self) -> list[dict]:
        return [{"kode": p, "teks": IZIN[p]} for p in self.permissions]

