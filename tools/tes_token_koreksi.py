"""
Gerbang token menu Koreksi: apakah token login portal diterima endpoint koreksi.

Skrip ini HANYA membaca. Tidak ada simulasi dan tidak ada POST koreksi.

Login memakai SSO IAM (popup kode enkripsi + jendela IAM), lalu GET data pelanggan ke dua endpoint koreksi untuk IDPEL
yang diberikan. Dengan satu IDPEL JN >= 720 dan satu JN < 720, sekaligus terjawab
bagaimana server merespons jalur yang tidak sesuai.

Kode enkripsi ditempel di popup, tidak dicetak, dan tidak disimpan. Token baru disimpan
ke billing_token.json folder ini seperti login biasa, jadi aplikasi dev bisa
memakainya. Keluaran tidak memuat token maupun nama pelanggan.

Pakai:
  python tools\\tes_token_koreksi.py --blth 202611 --idpel <JN_720_KE_ATAS> <JN_DI_BAWAH_720>

Tidak ikut terpaket: build.bat hanya mengacak main.py ui.py ui_dialogs.py
config.py core.
"""

import argparse
import base64
import json
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import BILLING_API_URL, BILLING_AUTH_URL, BILLING_TOKEN_FILE  # noqa: E402
from core.billing_client import (  # noqa: E402
    BillingAuthError, BillingClient, BillingError,
)
from core import sso_iam  # noqa: E402

ORIGIN = "http://10.68.35.109"
ENDPOINT = (
    ("720", "/api/data-koreksi-billing-720"),
    ("BILLING", "/api/data-koreksi-billing"),
)


def minta_kode_enkripsi():
    """Popup kode enkripsi. Return string, atau None kalau batal."""
    import tkinter as tk

    hasil = {}
    root = tk.Tk()
    root.title("Login SSO portal billing - tes token koreksi")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    tk.Label(root, text="Kode enkripsi (tempel); jendela IAM terbuka setelahnya").grid(
        row=0, column=0, sticky="w", padx=10, pady=(10, 0))
    t_kode = tk.Text(root, width=48, height=6)
    t_kode.grid(row=1, column=0, padx=10)

    def ok():
        hasil["kode"] = t_kode.get("1.0", "end").strip()
        root.destroy()

    tombol = tk.Frame(root)
    tombol.grid(row=2, column=0, pady=10)
    tk.Button(tombol, text="Lanjut", width=14, command=ok).pack(side="left", padx=5)
    tk.Button(tombol, text="Batal", width=10, command=root.destroy).pack(side="left", padx=5)
    t_kode.focus_set()
    root.mainloop()
    return hasil.get("kode") or None


def klaim_user(token):
    """Klaim `user` di JWT tanpa memverifikasi tanda tangan."""
    bagian = token.split(".")[1]
    bagian += "=" * (-len(bagian) % 4)
    return json.loads(base64.urlsafe_b64decode(bagian)).get("user") or {}


def ambil(client, path, idpel, blth):
    """Satu GET data pelanggan. Return ringkasan tanpa data pribadi."""
    headers = {
        "Accept": "application/json",
        "Origin": ORIGIN,
        "Referer": f"{ORIGIN}/",
    }
    resp = requests.get(
        f"{client.api_url}{path}",
        params={"idpel": idpel, "thblrek": blth},
        headers={**headers, "User-Agent": client.USER_AGENT,
                 "Authorization": f"Bearer {client.token}"},
        timeout=30,
    )
    try:
        isi = resp.json()
    except ValueError:
        return {"http": resp.status_code, "bukan_json": resp.text[:120]}
    data = isi.get("data") if isinstance(isi.get("data"), dict) else {}
    return {
        "http": resp.status_code,
        "success": isi.get("success"),
        "message": isi.get("message"),
        "thblrek": data.get("thblrek"),
        "unitup": data.get("unitup"),
        "jamNyala": data.get("jamNyala"),
        "lwbpAkhir": data.get("lwbpAkhir"),
        "ada_uraian": bool(data.get("uraianNilaiList")),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blth", required=True)
    parser.add_argument("--idpel", nargs="+", required=True)
    args = parser.parse_args()

    kode_enkripsi = minta_kode_enkripsi()
    if kode_enkripsi is None:
        print("Login dibatalkan.")
        return 1

    client = BillingClient(BILLING_AUTH_URL, BILLING_API_URL)
    try:
        kode = sso_iam.minta_kode(client.sso_url())
        if kode is None:
            print("Login SSO dibatalkan.")
            return 1
        if kode.get("code"):
            client.login_sso(kode["code"], kode["session_state"], kode_enkripsi)
        else:
            client.pakai_token(kode["token"], kode["account"])
    except (BillingAuthError, BillingError, sso_iam.SsoError) as e:
        print(f"Login gagal: {e}")
        return 1
    client.save_token(BILLING_TOKEN_FILE)
    user = klaim_user(client.token)
    print(f"Login OK. Unit {client.unitup}, userId token {len(str(user.get('userId', '')))} karakter.")

    diterima = False
    for idpel in args.idpel:
        print(f"\nIDPEL ...{idpel[-4:]}")
        for jalur, path in ENDPOINT:
            hasil = ambil(client, path, idpel, args.blth)
            print(f"  {jalur:8}", hasil)
            diterima = diterima or hasil.get("success") is True

    print("\nGERBANG:", "LOLOS, token portal diterima endpoint koreksi"
          if diterima else "TIDAK LOLOS, lihat pesan di atas")
    return 0 if diterima else 2


if __name__ == "__main__":
    sys.exit(main())
