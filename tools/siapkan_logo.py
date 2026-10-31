"""Siapkan aset logo SIMBA dari gambar mentah di logo_baru/.

Sekali jalan, hasilnya di-commit - aplikasi sendiri tidak memanggil skrip ini.

    python tools\\siapkan_logo.py [--pratinjau FOLDER]

Gambar sumber RGB tanpa alpha dengan latar putih: dipakai mentah, di tema gelap
logo tampil sebagai kotak putih. Latar dibuang lewat flood fill dari tepi gambar,
BUKAN ambang warna global - putih di dalam gambar (badan meter, kertas) harus
tetap utuh, dan hanya putih yang menyambung ke tepi yang memang latar.

Keluaran:
  assets/logo_simba.png   logo utuh transparan (dialog Tentang)
  assets/logo_emblem.png  emblem saja, persegi (header)
  assets/icon.ico         dari emblem - tulisan "SIMBA" tidak terbaca di 16-32 px
  icon.png                sama dengan icon.ico; build.bat membuat ico dari file ini
"""

import glob
import os
import sys

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOLERANSI = 12
# Baris di gambar sumber tempat emblem berakhir dan tulisan "SIMBA" dimulai.
BARIS_EMBLEM = 760
# Lebar pita tepi yang latarnya dilunakkan (color-to-alpha), dalam piksel.
PITA_TEPI = 4
UKURAN_SIMPAN = 512
UKURAN_ICO = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def buang_latar(img):
    rgb = np.array(img.convert("RGB"))
    h, w = rgb.shape[:2]
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8)
    tol = (TOLERANSI,) * 3

    # Benih di sepanjang tepi, bukan cuma sudut: sebagian tepi bisa terputus
    # dari sudut oleh bayangan/glow logo.
    tepi = ([(x, 0) for x in range(0, w, 8)] + [(x, h - 1) for x in range(0, w, 8)]
            + [(0, y) for y in range(0, h, 8)] + [(w - 1, y) for y in range(0, h, 8)])
    for x, y in tepi:
        if mask[y + 1, x + 1] == 0 and rgb[y, x].min() >= 255 - TOLERANSI:
            cv2.floodFill(bgr, mask, (x, y), 0, tol, tol, flags)

    latar = mask[1:-1, 1:-1] == 255
    # Di area tulisan tidak ada putih yang merupakan bagian gambar, jadi lubang
    # huruf (o, a, e) yang terkurung - tak tersentuh flood fill - ikut dibuang.
    # Kalau tidak, di tema gelap tampil sebagai titik-titik putih.
    latar[BARIS_EMBLEM:] |= rgb[BARIS_EMBLEM:].min(axis=2) >= 255 - TOLERANSI
    alpha = np.where(latar, 0, 255).astype(np.float32)
    warna = rgb.astype(np.float32)

    # Piksel di perbatasan latar biasanya campuran putih + warna logo; kalau
    # dibiarkan opaque, jadi garis putih tipis di tema gelap. Di pita itu saja
    # putih diubah jadi transparansi, supaya putih di tengah gambar tidak ikut.
    kernel = np.ones((2 * PITA_TEPI + 1,) * 2, np.uint8)
    pita = (cv2.dilate(latar.astype(np.uint8), kernel) > 0) & ~latar
    a = (255.0 - warna.min(axis=2)) / 255.0
    a_aman = np.maximum(a, 1e-3)[..., None]
    warna_pita = np.clip((warna - (1 - a[..., None]) * 255.0) / a_aman, 0, 255)
    alpha = np.where(pita, a * 255.0, alpha)
    warna = np.where(pita[..., None], warna_pita, warna)

    rgba = np.dstack([warna, alpha]).round().astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def potong_isi(img):
    return img.crop(img.getchannel("A").getbbox())


def jadikan_persegi(img):
    sisi = max(img.size)
    kanvas = Image.new("RGBA", (sisi, sisi), (0, 0, 0, 0))
    kanvas.paste(img, ((sisi - img.width) // 2, (sisi - img.height) // 2), img)
    return kanvas


def perkecil(img, sisi_maks):
    img = img.copy()
    img.thumbnail((sisi_maks, sisi_maks), Image.LANCZOS)
    return img


def pratinjau(img, path):
    """Tempel di atas latar gelap (tema darkly) dan terang berdampingan."""
    lebar, tinggi = img.size
    kanvas = Image.new("RGBA", (lebar * 2, tinggi), (34, 34, 34, 255))
    kanvas.paste((255, 255, 255, 255), (lebar, 0, lebar * 2, tinggi))
    kanvas.alpha_composite(img, (0, 0))
    kanvas.alpha_composite(img, (lebar, 0))
    kanvas.convert("RGB").save(path)


def main(argv):
    sumber = sorted(glob.glob(os.path.join(ROOT, "logo_baru", "*.png")))
    if not sumber:
        print("Tidak ada PNG di logo_baru/")
        return 1
    print(f"Sumber: {sumber[0]}")

    bersih = buang_latar(Image.open(sumber[0]))
    logo = perkecil(potong_isi(bersih), UKURAN_SIMPAN)
    emblem = jadikan_persegi(potong_isi(bersih.crop((0, 0, bersih.width, BARIS_EMBLEM))))
    # Icon memakai emblem utuh. Crop lebih rapat (petir + meter saja) sudah
    # dicoba: memang lebih besar di 16 px, tapi meternya terpotong kasar di tepi.
    ikon = emblem

    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    keluaran = {
        "assets/logo_simba.png": logo,
        "assets/logo_emblem.png": perkecil(emblem, UKURAN_SIMPAN),
        "icon.png": perkecil(ikon, UKURAN_SIMPAN),
    }
    for rel, img in keluaran.items():
        img.save(os.path.join(ROOT, rel), optimize=True)
        print(f"  {rel} {img.size}")

    perkecil(ikon, 256).save(os.path.join(ROOT, "assets", "icon.ico"), sizes=UKURAN_ICO)
    print("  assets/icon.ico")

    if "--pratinjau" in argv:
        folder = argv[argv.index("--pratinjau") + 1]
        os.makedirs(folder, exist_ok=True)
        pratinjau(perkecil(logo, 400), os.path.join(folder, "pratinjau_logo.png"))
        pratinjau(perkecil(emblem, 256), os.path.join(folder, "pratinjau_emblem.png"))
        # Ukuran kecil diperbesar tanpa haluskan supaya keterbacaan icon kelihatan.
        kecil = Image.new("RGBA", (16 + 32 + 48 + 40, 48), (0, 0, 0, 0))
        x = 0
        for s in (16, 32, 48):
            kecil.alpha_composite(perkecil(ikon, s), (x, 0))
            x += s + 20
        kecil = kecil.resize((kecil.width * 4, kecil.height * 4), Image.NEAREST)
        pratinjau(kecil, os.path.join(folder, "pratinjau_icon_kecil.png"))
        print(f"  pratinjau -> {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
