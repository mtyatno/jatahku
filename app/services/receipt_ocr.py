"""OCR struk dengan RapidOCR (model PaddleOCR via ONNX Runtime, CPU, tanpa LLM).

Entry point: await read_receipt_lines(image_bytes) -> OcrResult.

- Model dimuat sekali (lazy) dan dipakai ulang; ±340 MB RAM.
- Hanya 1 OCR berjalan bersamaan (semaphore) supaya API & bot di VPS 4GB
  tidak tersendat; OCR dijalankan di thread agar event loop tetap responsif.
- build_lines() murni (tanpa model) supaya bisa di-test.
"""
from __future__ import annotations

import asyncio
import io
import os
from dataclasses import dataclass

# Batas piksel untuk decoder OpenCV (default ±1 gigapiksel bisa >3 GB RAM).
# Harus di-set sebelum cv2 diimpor pertama kali.
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(40_000_000))

MAX_SIDE = 2000  # foto HP besar diperkecil dulu: lebih cepat, akurasi tetap
# Tumpang-tindih vertikal minimum agar dua kotak dianggap sebaris. Baris yang
# bersebelahan di struk praktis tidak bertumpang-tindih, jadi 0.35 aman dan
# masih menangkap kertas yang melengkung.
MIN_OVERLAP = 0.35
# Foto HP 50 MP masih lolos; gambar raksasa (bom dekompresi: PNG kecil
# 16000×16000) ditolak sebelum didekode.
MAX_PIXELS = 30_000_000
# Antrean OCR: lebih dari ini yang menunggu → tolak (503) daripada menumpuk.
MAX_WAITING = 4


class OcrUnavailable(Exception):
    """Paket rapidocr/onnxruntime belum terpasang di server."""


class OcrFailed(Exception):
    """Gambar rusak / tidak bisa didekode / terlalu besar."""


class OcrBusy(Exception):
    """Antrean OCR penuh atau scan user ini masih berjalan."""


@dataclass
class OcrResult:
    lines: list[str]
    score: float  # rata-rata keyakinan OCR 0..1
    seconds: float


@dataclass
class _Box:
    x0: float
    x1: float
    y0: float
    y1: float
    text: str

    @property
    def height(self) -> float:
        return max(1.0, self.y1 - self.y0)

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def _vertical_overlap(a: _Box, b: _Box) -> float:
    inter = min(a.y1, b.y1) - max(a.y0, b.y0)
    return max(0.0, inter) / min(a.height, b.height)


def build_lines(boxes, texts) -> list[str]:
    """Susun kotak teks OCR menjadi baris.

    Kotak diproses dari kiri ke kanan; tiap kotak menyambung ke baris yang kotak
    terakhirnya (paling kanan) paling bertumpang-tindih secara vertikal. Dengan
    begitu baris mengikuti lengkungan kertas, dan label kiri ("TUNAI") tetap
    berpasangan dengan nominal di kanannya walau struk melengkung.
    """
    items = []
    for box, txt in zip(boxes, texts):
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        if str(txt).strip():
            items.append(_Box(min(xs), max(xs), min(ys), max(ys), str(txt).strip()))
    items.sort(key=lambda b: b.x0)

    lines: list[list[_Box]] = []
    for box in items:
        best, best_ov = None, 0.0
        for line in lines:
            last = line[-1]
            if box.x0 < last.x1 - last.height:  # tumpang-tindih horizontal → beda baris
                continue
            ov = _vertical_overlap(box, last)
            if ov > best_ov:
                best, best_ov = line, ov
        if best is not None and best_ov >= MIN_OVERLAP:
            best.append(box)
        else:
            lines.append([box])

    lines.sort(key=lambda l: sum(b.cy for b in l) / len(l))
    return ["  ".join(b.text for b in line) for line in lines]


_engine = None
_engine_lock = asyncio.Lock()
_ocr_slot = asyncio.Semaphore(1)


def _load_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:  # pragma: no cover - tergantung server
        raise OcrUnavailable("rapidocr belum terpasang") from exc
    return RapidOCR()


def check_dimensions(image_bytes: bytes) -> None:
    """Baca ukuran dari header gambar (tanpa dekode) dan tolak yang kebesaran."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            width, height = im.size
    except Exception as exc:  # format tak dikenal, rusak, atau DecompressionBombError
        raise OcrFailed("gambar tidak bisa dibaca") from exc
    if width * height > MAX_PIXELS:
        raise OcrFailed("resolusi gambar terlalu besar")


def _run_ocr(engine, image_bytes: bytes) -> OcrResult:
    import time

    import cv2
    import numpy as np

    t0 = time.time()
    check_dimensions(image_bytes)
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise OcrFailed("gambar tidak bisa dibaca")
    h, w = img.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    res = engine(img)
    if res is None or res.boxes is None or not len(res.boxes):
        return OcrResult(lines=[], score=0.0, seconds=time.time() - t0)
    scores = [float(s) for s in (res.scores or [])]
    return OcrResult(
        lines=build_lines(res.boxes, res.txts),
        score=sum(scores) / len(scores) if scores else 0.0,
        seconds=time.time() - t0,
    )


_waiting = 0
_in_flight: set = set()


async def read_receipt_lines(image_bytes: bytes, owner=None) -> OcrResult:
    """OCR satu foto. `owner` (user id) membatasi 1 scan berjalan per user.

    Catatan: batas "1 OCR bersamaan" berlaku per proses — jalankan uvicorn
    dengan 1 worker (setiap worker memuat model sendiri, ±340 MB).
    """
    global _engine, _waiting
    if owner is not None and owner in _in_flight:
        raise OcrBusy("scan sebelumnya masih diproses")
    if _waiting >= MAX_WAITING:
        raise OcrBusy("antrean scan penuh")
    check_dimensions(image_bytes)  # tolak cepat sebelum masuk antrean
    if owner is not None:
        _in_flight.add(owner)
    _waiting += 1
    queued = True
    try:
        async with _engine_lock:
            if _engine is None:
                _engine = await asyncio.to_thread(_load_engine)
        async with _ocr_slot:
            _waiting -= 1  # keluar antrean, mulai diproses
            queued = False
            return await asyncio.to_thread(_run_ocr, _engine, image_bytes)
    finally:
        if queued:
            _waiting -= 1
        if owner is not None:
            _in_flight.discard(owner)
