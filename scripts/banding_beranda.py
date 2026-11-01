"""Plugin B3 — banding tampilan Beranda lama vs Beranda registry di akun sendiri (Gerbang B, tampilan).

Membuka `/?beranda=lama` dan `/?beranda=registry` (Dashboard.jsx memaksa salah satu) di Chrome
headless pada 390, 820, 1100, dan 1440 px, tema gelap dan terang, lalu membandingkan screenshot
per piksel. Data dan izin tetap dari server: alat ini hanya membaca Beranda akunmu sendiri.

Dijalankan di laptop (bukan VPS), butuh Python dengan `playwright` dan `pillow`, plus Chrome:
    pip install playwright pillow && python -m playwright install chromium   # atau --chrome /path
    read -s JATAHKU_TOKEN && export JATAHKU_TOKEN   # tempel localStorage 'jatahku_token'; tidak masuk riwayat
    python scripts/banding_beranda.py --out /tmp/banding && unset JATAHKU_TOKEN

Token akses hanya dibaca dari env, tidak pernah ditulis ke disk atau dicetak; berlaku singkat.
Hasil: `<out>/<tema>-<lebar>-{lama,registry,beda}.png` dan ringkasan. Kode keluar 1 bila ada yang beda.
Lokal: `--url http://localhost:5173` dengan Vite + API lokal (lihat SESI-LOG B2).
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

LEBAR = (390, 820, 1100, 1440)
TEMA = ("dark", "light")


async def tangkap(browser, url, token, lebar, tema, mode, out: Path):
    ctx = await browser.new_context(viewport={"width": lebar, "height": 900}, timezone_id="Asia/Jakarta",
                                    locale="id-ID", device_scale_factor=1, reduced_motion="reduce")
    # Token disuntik lewat init script di memori browser; modal Telegram ditandai sudah tampil.
    await ctx.add_init_script(
        "localStorage.setItem('jatahku_token', %r);"
        "localStorage.setItem('jatahku_tg_prompt_last_shown', String(Date.now()));"
        "localStorage.setItem('jatahku_theme', JSON.stringify({color: 'hijau', mode: %r}));" % (token, tema))
    page = await ctx.new_page()
    api = []
    page.on("request", lambda r: api.append(r.url) if r.resource_type in ("fetch", "xhr") else None)
    tujuan = f"{url}/?beranda={mode}"
    await page.goto(tujuan, wait_until="networkidle")
    await page.wait_for_timeout(1500)
    api.clear()
    await page.reload(wait_until="networkidle")      # kunjungan kedua: tata letak sudah di cache
    await page.wait_for_timeout(2500)
    if "/login" in page.url:
        await ctx.close()
        raise SystemExit("Token tidak berlaku (dialihkan ke /login). Ambil token baru dari jatahku.com.")
    path = out / f"{tema}-{lebar}-{mode}.png"
    await page.screenshot(path=str(path), full_page=True)
    await ctx.close()
    return path, len(api)


def banding(a: Path, b: Path, beda_path: Path) -> str:
    from PIL import Image, ImageChops
    A, B = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if A.size != B.size:
        return f"BEDA ukuran {A.size} vs {B.size}"
    d = ImageChops.difference(A, B)
    kotak = d.getbbox()
    if kotak is None:
        return "identik"
    d.point(lambda v: 255 if v else 0).save(beda_path)
    return f"BEDA di area {kotak}"


async def jalankan(url, token, out: Path, chrome=None) -> int:
    from playwright.async_api import async_playwright
    out.mkdir(parents=True, exist_ok=True)
    gagal = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chrome, args=["--no-sandbox"] if chrome else None)
        for tema in TEMA:
            for lebar in LEBAR:
                a, na = await tangkap(browser, url, token, lebar, tema, "lama", out)
                b, nb = await tangkap(browser, url, token, lebar, tema, "registry", out)
                hasil = banding(a, b, out / f"{tema}-{lebar}-beda.png")
                gagal += hasil != "identik"
                print(f"{tema:5} {lebar:5} px  {hasil:40}  permintaan API: lama {na} · registry {nb}")
        await browser.close()
    print("Tampilan: " + ("SAMA di semua lebar dan tema" if not gagal else f"{gagal} kombinasi BEDA (lihat *-beda.png)"))
    return 1 if gagal else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="https://jatahku.com")
    ap.add_argument("--out", default="banding-beranda")
    ap.add_argument("--chrome", default=None, help="path Chrome/Chromium bila bukan bawaan Playwright")
    args = ap.parse_args(argv)
    token = os.environ.get("JATAHKU_TOKEN", "").strip()
    if not token:
        print("Isi env JATAHKU_TOKEN dengan localStorage 'jatahku_token' dari browser yang sedang login.")
        return 2
    return asyncio.run(jalankan(args.url.rstrip("/"), token, Path(args.out), args.chrome))


if __name__ == "__main__":
    sys.exit(main())
