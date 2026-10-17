"""Mobile 1.4 — cek perubahan API yang memutus (ADR-M9, aturan mobile #2 di AGENTS.md).

Aplikasi yang sudah terpasang menjalankan kode lama berminggu-minggu, jadi API hanya boleh
bertambah. Skrip ini membandingkan skema OpenAPI FastAPI di commit dasar (mis. `main`)
dengan kode sekarang dan gagal bila ada yang memutus klien lama:

- path atau method hilang; kode respons 2xx hilang;
- respons: field hilang, field wajib jadi opsional, tipe berubah atau bertambah (mis. bisa `null`);
- request: parameter/field wajib baru, parameter/field jadi wajib, tipe menyempit,
  nilai enum hilang, body jadi wajib.

Respons tanpa `response_model` (skema `{}`) tidak bisa diperiksa; field di sana tidak terlihat.
Nilai enum baru di respons hanya peringatan.

Lokal (dari root repo):
    python -m app.scripts.openapi_cek                    # bandingkan dengan origin/main
    python -m app.scripts.openapi_cek --dasar <ref>
    python -m app.scripts.openapi_cek bandingkan dasar.json baru.json

Keluar dengan kode 1 bila ada perubahan memutus, 2 bila skema tidak bisa diekspor. Perubahan yang disengaja: label PR
`api-memutus` (lihat .github/workflows/openapi.yml), hanya setelah `min_supported_version`
di /app/config dinaikkan.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

METHODS = ("get", "put", "post", "delete", "patch", "options", "head")

EKSPOR = (
    "import json, sys; from app.main import app; "
    "json.dump(app.openapi(), sys.stdout, sort_keys=True)"
)


# ── normalisasi skema ────────────────────────────────────────────────

class _Skema:
    """Pembantu untuk satu dokumen OpenAPI: resolusi $ref dan perataan anyOf/oneOf/allOf."""

    def __init__(self, doc: dict):
        self.doc = doc

    def resolve(self, s):
        seen = set()
        while isinstance(s, dict) and "$ref" in s:
            ref = s["$ref"]
            if ref in seen:
                return {}
            seen.add(ref)
            node = self.doc
            for part in ref.lstrip("#/").split("/"):
                node = node.get(part, {}) if isinstance(node, dict) else {}
            s = node
        return s if isinstance(s, dict) else {}

    def varian(self, s) -> list:
        """Skema diratakan menjadi daftar varian tanpa anyOf/oneOf; allOf digabung."""
        s = self.resolve(s)
        if "allOf" in s:
            gabung = {k: v for k, v in s.items() if k != "allOf"}
            for bagian in s["allOf"]:
                for v in self.varian(bagian):
                    for k, val in v.items():
                        if k == "properties":
                            gabung.setdefault("properties", {}).update(val)
                        elif k == "required":
                            gabung["required"] = sorted(set(gabung.get("required", [])) | set(val))
                        else:
                            gabung.setdefault(k, val)
            return [gabung]
        for kunci in ("anyOf", "oneOf"):
            if kunci in s:
                hasil = []
                for bagian in s[kunci]:
                    hasil.extend(self.varian(bagian))
                return hasil
        return [s]

    def tipe(self, s) -> set:
        hasil = set()
        for v in self.varian(s):
            t = v.get("type")
            if isinstance(t, list):
                hasil.update(t)
            elif t:
                hasil.add(t)
            elif "properties" in v:
                hasil.add("object")
            elif v.get("nullable"):
                pass
            else:
                hasil.add("*")  # skema bebas: apa saja
            if v.get("nullable"):
                hasil.add("null")
        return hasil

    def properti(self, s) -> tuple:
        """(properties, required) dari semua varian objek."""
        props, wajib, ada_objek = {}, None, False
        for v in self.varian(s):
            if "properties" in v or v.get("type") == "object":
                ada_objek = True
                props.update(v.get("properties", {}))
                req = set(v.get("required", []))
                wajib = req if wajib is None else wajib & req
        return props, (wajib or set()), ada_objek

    def items(self, s):
        daftar = [v["items"] for v in self.varian(s) if "items" in v]
        if not daftar:
            return None
        return daftar[0] if len(daftar) == 1 else {"anyOf": daftar}

    def enum(self, s):
        nilai, terbatas = set(), True
        for v in self.varian(s):
            if "enum" in v:
                nilai.update(json.dumps(x, sort_keys=True) for x in v["enum"])
            elif "const" in v:
                nilai.add(json.dumps(v["const"], sort_keys=True))
            elif v.get("type") != "null":
                terbatas = False
        return nilai if terbatas and nilai else None


def _bebas(tipe: set) -> bool:
    return not tipe or "*" in tipe


# ── perbandingan ─────────────────────────────────────────────────────

class Pembanding:
    def __init__(self, dasar: dict, baru: dict):
        self.a = _Skema(dasar)
        self.b = _Skema(baru)
        self.memutus: list[str] = []
        self.peringatan: list[str] = []

    def _putus(self, lokasi, pesan):
        self.memutus.append(f"{lokasi}: {pesan}")

    def _ingat(self, lokasi, pesan):
        self.peringatan.append(f"{lokasi}: {pesan}")

    def jalankan(self):
        pa = self.a.doc.get("paths", {})
        pb = self.b.doc.get("paths", {})
        for path in sorted(pa):
            if path not in pb:
                self._putus(path, "path dihapus")
                continue
            for m in METHODS:
                if m not in pa[path]:
                    continue
                lokasi = f"{m.upper()} {path}"
                if m not in pb[path]:
                    self._putus(lokasi, "method dihapus")
                    continue
                self._operasi(lokasi, pa[path][m], pb[path][m])
        return self

    def _operasi(self, lokasi, oa, ob):
        self._parameter(lokasi, oa.get("parameters", []), ob.get("parameters", []))

        ba = self.a.resolve(oa.get("requestBody")) if oa.get("requestBody") else None
        bb = self.b.resolve(ob.get("requestBody")) if ob.get("requestBody") else None
        if bb and bb.get("required") and not (ba and ba.get("required")):
            self._putus(lokasi, "body request jadi wajib")
        if ba and bb:
            for ctype, ca in ba.get("content", {}).items():
                cb = bb.get("content", {}).get(ctype)
                if cb is None:
                    self._putus(lokasi, f"body request {ctype} tidak diterima lagi")
                    continue
                self._req(f"{lokasi} body", ca.get("schema", {}), cb.get("schema", {}), set())

        ra, rb = oa.get("responses", {}), ob.get("responses", {})
        for kode in sorted(ra):
            if not str(kode).startswith("2"):
                continue
            if kode not in rb:
                self._putus(lokasi, f"respons {kode} hilang")
                continue
            ka = self.a.resolve(ra[kode]).get("content", {})
            kb = self.b.resolve(rb[kode]).get("content", {})
            for ctype, ca in ka.items():
                cb = kb.get(ctype)
                if cb is None:
                    self._putus(lokasi, f"respons {kode} tidak lagi {ctype}")
                    continue
                self._resp(f"{lokasi} → {kode}", ca.get("schema", {}), cb.get("schema", {}), set())

    def _parameter(self, lokasi, la, lb):
        da = {(p["in"], p["name"]): p for p in map(self.a.resolve, la)}
        db = {(p["in"], p["name"]): p for p in map(self.b.resolve, lb)}
        for kunci, pb in db.items():
            nama = f"{kunci[0]} `{kunci[1]}`"
            pa = da.get(kunci)
            if pa is None:
                if pb.get("required"):
                    self._putus(lokasi, f"parameter wajib baru {nama}")
                continue
            if pb.get("required") and not pa.get("required"):
                self._putus(lokasi, f"parameter {nama} jadi wajib")
            self._req(f"{lokasi} parameter {nama}", pa.get("schema", {}), pb.get("schema", {}), set())

    # Request: klien lama mengirim bentuk lama; server baru harus tetap menerimanya.
    def _req(self, lokasi, sa, sb, jejak):
        kunci = (id(sa), id(sb))
        if kunci in jejak:
            return
        jejak = jejak | {kunci}
        ta, tb = self.a.tipe(sa), self.b.tipe(sb)
        if _bebas(ta) and _bebas(tb):
            return
        if not _bebas(tb):
            hilang = ta - tb - ({"integer"} if "number" in tb else set())
            if _bebas(ta) or hilang:
                self._putus(lokasi, f"tipe menyempit {_fmt(ta)} → {_fmt(tb)}")
                return
        ea, eb = self.a.enum(sa), self.b.enum(sb)
        if eb is not None and (ea is None or ea - eb):
            hilang = sorted(ea - eb) if ea is not None else ["(sebelumnya bebas)"]
            self._putus(lokasi, f"nilai enum tidak diterima lagi: {', '.join(hilang)}")
        pa, wa, _ = self.a.properti(sa)
        pb, wb, _ = self.b.properti(sb)
        for nama in sorted(pb):
            if nama not in pa:
                if nama in wb:
                    self._putus(lokasi, f"field wajib baru `{nama}`")
                continue
            if nama in wb and nama not in wa:
                self._putus(lokasi, f"field `{nama}` jadi wajib")
            self._req(f"{lokasi}.{nama}", pa[nama], pb[nama], jejak)
        ia, ib = self.a.items(sa), self.b.items(sb)
        if ia is not None and ib is not None:
            self._req(f"{lokasi}[]", ia, ib, jejak)

    # Respons: klien lama membaca bentuk lama; server baru harus tetap mengirimnya.
    def _resp(self, lokasi, sa, sb, jejak):
        kunci = (id(sa), id(sb))
        if kunci in jejak:
            return
        jejak = jejak | {kunci}
        ta, tb = self.a.tipe(sa), self.b.tipe(sb)
        if _bebas(ta):
            return
        if _bebas(tb):
            self._ingat(lokasi, "skema respons tidak lagi tercatat (response_model dilepas?)")
            return
        baru = tb - ta - ({"integer"} if "number" in ta else set())
        if baru:
            self._putus(lokasi, f"tipe berubah {_fmt(ta)} → {_fmt(tb)}")
            return
        ea, eb = self.a.enum(sa), self.b.enum(sb)
        if ea is not None and (eb is None or eb - ea):
            tambah = sorted(eb - ea) if eb is not None else ["(jadi bebas)"]
            self._ingat(lokasi, f"nilai enum baru: {', '.join(tambah)}")
        pa, wa, _ = self.a.properti(sa)
        pb, wb, _ = self.b.properti(sb)
        for nama in sorted(pa):
            if nama not in pb:
                self._putus(lokasi, f"field `{nama}` dihapus")
                continue
            if nama in wa and nama not in wb:
                self._putus(lokasi, f"field `{nama}` tidak lagi selalu ada")
            self._resp(f"{lokasi}.{nama}", pa[nama], pb[nama], jejak)
        ia, ib = self.a.items(sa), self.b.items(sb)
        if ia is not None and ib is not None:
            self._resp(f"{lokasi}[]", ia, ib, jejak)


def _fmt(tipe: set) -> str:
    return "|".join(sorted(tipe)) or "*"


def bandingkan(dasar: dict, baru: dict) -> Pembanding:
    return Pembanding(dasar, baru).jalankan()


# ── ekspor ───────────────────────────────────────────────────────────

def _env():
    env = dict(os.environ)
    env.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    env.setdefault("JWT_SECRET", "openapi-cek")
    env["PYTHONPATH"] = ""
    return env


def ekspor(root: str) -> dict:
    """Skema OpenAPI dari kode di `root`, di proses terpisah (paket `app` tidak tercampur)."""
    hasil = subprocess.run(
        [sys.executable, "-c", EKSPOR], cwd=root, env=_env(),
        capture_output=True, text=True, check=False,
    )
    if hasil.returncode != 0:
        raise RuntimeError(f"gagal mengekspor OpenAPI di {root}:\n{hasil.stderr[-2000:]}")
    return json.loads(hasil.stdout)


def ekspor_ref(ref: str) -> dict:
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="openapi-dasar-") as tmp:
        pohon = os.path.join(tmp, "dasar")
        subprocess.run(["git", "worktree", "add", "--detach", "--quiet", pohon, ref], cwd=root, check=True,
                       stdout=subprocess.DEVNULL)
        try:
            return ekspor(pohon)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", pohon], cwd=root, check=False)


# ── keluaran ─────────────────────────────────────────────────────────

def laporan(p: Pembanding) -> str:
    baris = []
    if p.memutus:
        baris.append(f"### ❌ {len(p.memutus)} perubahan API memutus aplikasi lama")
        baris += [f"- {m}" for m in p.memutus]
        baris.append("")
        baris.append("API hanya boleh bertambah (ADR-M9, AGENTS.md aturan mobile #2). Kembalikan "
                     "field/endpoint lama, atau tambahkan yang baru di sampingnya.")
    else:
        baris.append("### ✅ Tidak ada perubahan API yang memutus")
    if p.peringatan:
        baris.append("")
        baris.append(f"Peringatan ({len(p.peringatan)}), tidak menggagalkan:")
        baris += [f"- {m}" for m in p.peringatan]
    return "\n".join(baris)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="perintah")
    b = sub.add_parser("bandingkan", help="bandingkan dua file JSON OpenAPI")
    b.add_argument("dasar")
    b.add_argument("baru")
    e = sub.add_parser("ekspor", help="tulis OpenAPI kode sekarang ke stdout")
    e.add_argument("--root", default=".")
    ap.add_argument("--dasar", default="origin/main", help="git ref pembanding (bawaan origin/main)")
    ap.add_argument("--ringkasan", help="tulis laporan Markdown juga ke file ini (mis. $GITHUB_STEP_SUMMARY)")
    args = ap.parse_args(argv)

    if args.perintah == "ekspor":
        json.dump(ekspor(args.root), sys.stdout, sort_keys=True, indent=1)
        return 0
    if args.perintah == "bandingkan":
        with open(args.dasar) as f:
            dasar = json.load(f)
        with open(args.baru) as f:
            baru = json.load(f)
    else:
        try:
            dasar = ekspor_ref(args.dasar)
            baru = ekspor(".")
        except (RuntimeError, subprocess.CalledProcessError) as e:
            print(f"Cek OpenAPI tidak bisa jalan: {e}", file=sys.stderr)
            return 2

    p = bandingkan(dasar, baru)
    teks = laporan(p)
    print(teks)
    if args.ringkasan:
        with open(args.ringkasan, "a") as f:
            f.write(teks + "\n")
    return 1 if p.memutus else 0


if __name__ == "__main__":
    sys.exit(main())
