"""
Tes unduh foto ACMT untuk SATU IDPEL lewat popup login (2026-10).

Sejak 2026-10 foto baru disimpan di S3: amplop /acmt/download/photo/meter/...
membawa `data.url` (presigned, X-Amz-Signature, port 8086) alih-alih
`data.urlPhoto` (NFS). Skrip ini memakai SimbaClient aplikasi apa adanya
(download_foto yang sama dengan pipeline), jadi yang teruji adalah kode
aplikasi, bukan tiruannya.

Kredensial diketik di popup dan hanya dipakai untuk login; tidak dicetak dan
tidak disimpan. Sesi SELALU di-logout di akhir.

Pakai:
  python tools\\tes_foto_idpel.py --idpel 443200097996 --blth 202611 --out <folder>

Tidak ikut terpaket: build.bat hanya mengacak main.py ui.py ui_dialogs.py
config.py core.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import SIMBA_BASE_URL  # noqa: E402
from core.simba_client import SimbaClient, adalah_gambar  # noqa: E402


def minta_login():
    """Popup login ACMT. Return (user, password, kode) atau None kalau batal."""
    import tkinter as tk

    hasil = {}
    root = tk.Tk()
    root.title("Login ACMT - tes foto")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    tk.Label(root, text="Username ACMT (mis. 44320.nama)").grid(
        row=0, column=0, sticky="w", padx=10, pady=(10, 0))
    e_user = tk.Entry(root, width=48)
    e_user.grid(row=1, column=0, padx=10)

    tk.Label(root, text="Password").grid(row=2, column=0, sticky="w", padx=10, pady=(8, 0))
    e_pass = tk.Entry(root, width=48, show="*")
    e_pass.grid(row=3, column=0, padx=10)

    tk.Label(root, text="Kode enkripsi (tempel)").grid(
        row=4, column=0, sticky="w", padx=10, pady=(8, 0))
    t_kode = tk.Text(root, width=48, height=6)
    t_kode.grid(row=5, column=0, padx=10)

    def ok():
        hasil["user"] = e_user.get().strip()
        hasil["pass"] = e_pass.get()
        hasil["kode"] = t_kode.get("1.0", "end").strip()
        root.destroy()

    def batal():
        root.destroy()

    tombol = tk.Frame(root)
    tombol.grid(row=6, column=0, pady=10)
    tk.Button(tombol, text="Login & Tes", width=14, command=ok).pack(side="left", padx=5)
    tk.Button(tombol, text="Batal", width=10, command=batal).pack(side="left", padx=5)
    root.protocol("WM_DELETE_WINDOW", batal)
    e_user.focus_set()
    root.mainloop()

    if not hasil or not hasil["user"] or not hasil["pass"] or not hasil["kode"]:
        return None
    return hasil["user"], hasil["pass"], hasil["kode"]


def jenis_amplop(client, url):
    """GET pathFoto mentah: laporkan storage + field URL yang dipakai server."""
    try:
        resp = client.session.get(url, timeout=30,
                                  headers={"accept": "application/json, */*"})
    except Exception as e:
        return f"request gagal: {e}"
    ctype = (resp.headers.get("content-type") or "").lower()
    if "json" not in ctype:
        return f"HTTP {resp.status_code}, bukan amplop ({ctype or '-'})"
    try:
        isi = (resp.json() or {}).get("data") or {}
    except ValueError:
        return f"HTTP {resp.status_code}, JSON rusak"
    medan = [k for k in ("url", "urlPhoto") if isi.get(k)]
    return f"HTTP {resp.status_code}, storage={isi.get('storage')}, field={medan or 'TIDAK ADA'}"


def dimensi(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return f"{im.size[0]}x{im.size[1]}"
    except Exception as e:
        return f"tidak terbaca ({e})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idpel", required=True)
    ap.add_argument("--blth", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    login = minta_login()
    if login is None:
        print("Login dibatalkan - tidak ada yang dites.")
        return 3
    user, pw, kode = login

    client = SimbaClient(SIMBA_BASE_URL)
    try:
        client.login(user, pw, kode)
    except Exception as e:
        print(f"LOGIN GAGAL: {e}")
        return 3
    print(f"Login ACMT berhasil (unit {client.unitup})")

    n_ok = n_gagal = 0
    try:
        records = client.get_info_pelanggan(args.idpel, args.blth)
        print(f"infopelanggan {args.idpel} blth {args.blth}: {len(records)} record")
        for rec in records:
            bln = str(rec.get("blth") or "?")
            fotos = [u for item in (rec.get("pathFoto") or []) if isinstance(item, dict)
                     for u in item.values() if u]
            if not fotos:
                print(f"  {bln}: tidak ada pathFoto")
                continue
            for i, url in enumerate(fotos, 1):
                nama = os.path.basename(url.split("?")[0]) or f"{args.idpel}_{bln}_{i}.jpg"
                path = os.path.join(args.out, bln, nama)
                print(f"  {bln} foto{i}: {jenis_amplop(client, url)}")
                ok = client.download_foto(url, path)
                if ok and os.path.exists(path):
                    with open(path, "rb") as f:
                        awal = f.read(8)
                    n_ok += 1
                    print(f"      -> OK {os.path.getsize(path):,} byte, "
                          f"gambar={adalah_gambar(awal)}, {dimensi(path)}")
                    print(f"         {path}")
                else:
                    n_gagal += 1
                    print("      -> GAGAL (download_foto return False)")
    finally:
        ok, pesan = client.logout()
        print("Logout ACMT berhasil" if ok else f"Logout ACMT gagal: {pesan}")

    print(f"\nRINGKASAN: {n_ok} foto OK, {n_gagal} gagal")
    return 0 if n_gagal == 0 and n_ok > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
