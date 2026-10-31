"""
Tes unduh foto SIMBA setelah endpoint berubah (2026-09).

URL pathFoto (/acmt/download/photo/meter/...) sekarang membalas amplop JSON
{data: {storage, urlPhoto}}; download_foto harus mengikuti urlPhoto sekali dan
hanya menyimpan file yang benar-benar gambar. Skrip ini memisahkan dua hal:

  OFFLINE  logika billing v3 benar (tanpa SIMBA): _url_dari_amplop,
           adalah_gambar, _foto_valid, dan download_foto ujung-ke-ujung
           melawan server tiruan di localhost.
  ONLINE   server SIMBA benar-benar mengirim foto: diagnosis mentah per
           langkah + download_foto asli ke folder temp (bukan FOTO_DIR).

Tidak ikut terpaket: build.bat hanya mengacak main.py ui.py ui_dialogs.py
config.py core.

Pakai:
  python tools\\tes_unduh_foto.py --offline
  python tools\\tes_unduh_foto.py --idpel 443200114624 443200047307
  python tools\\tes_unduh_foto.py --login          (login baru, logout di akhir)

Exit code: 0 lolos, 1 kode salah, 2 kode benar tapi server tidak mengirim foto.
"""

import argparse
import getpass
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import SIMBA_BASE_URL  # noqa: E402
from core.photo import _foto_valid  # noqa: E402
from core.simba_client import (  # noqa: E402
    SimbaAuthError,
    SimbaClient,
    SimbaError,
    adalah_gambar,
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PENGATURAN_OTOMASI = r"D:\python\cari foto revas billing\LAMPIRAN\otomasi\pengaturan.json"
IDPEL_DEFAULT = ["443200114624", "443200047307"]
ACCEPT_FOTO = "image/jpeg, image/*, */*"   # sama dengan _unduh_atau_arahkan

JPEG_PALSU = b"\xff\xd8\xff\xe0" + b"\x00" * 600 + b"\xff\xd9"
PNG_AWAL = b"\x89PNG\r\n\x1a\n"


class Hasil:
    def __init__(self):
        self.lolos = 0
        self.gagal = 0

    def cek(self, nama, kondisi, detail=""):
        if kondisi:
            self.lolos += 1
            print(f"  PASS  {nama}")
        else:
            self.gagal += 1
            print(f"  FAIL  {nama}" + (f"  -> {detail}" if detail else ""))
        return kondisi


def _amplop(url_photo, storage="NFS"):
    return json.dumps({
        "code": 200, "success": True, "message": "Data ditemukan",
        "data": {"storage": storage, "urlPhoto": url_photo},
    }).encode()


# =========================
# OFFLINE
# =========================

def tes_offline():
    print("\n=== A. OFFLINE (tanpa SIMBA) ===")
    h = Hasil()

    print("-- _url_dari_amplop")
    url = "http://x/acmt/download/photo/meternfs/44320/202609/a.jpg"
    h.cek("amplop sukses -> urlPhoto", SimbaClient._url_dari_amplop(_amplop(url)) == url)
    h.cek("urlPhoto kosong -> False", SimbaClient._url_dari_amplop(_amplop("")) is False)
    h.cek("bukan JSON -> False", SimbaClient._url_dari_amplop(b"<html>") is False)
    try:
        SimbaClient._url_dari_amplop(json.dumps(
            {"success": False, "message": "Token required atau format salah"}).encode())
        h.cek("success:false pesan token -> SimbaAuthError", False, "tidak raise")
    except SimbaAuthError:
        h.cek("success:false pesan token -> SimbaAuthError", True)

    print("-- adalah_gambar")
    h.cek("JPEG -> True", adalah_gambar(JPEG_PALSU[:4]))
    h.cek("PNG -> True", adalah_gambar(PNG_AWAL[:4]))
    h.cek("JSON -> False", not adalah_gambar(_amplop(url)[:4]))
    h.cek("kosong -> False", not adalah_gambar(b""))

    tmp = tempfile.mkdtemp(prefix="tes_foto_offline_")
    try:
        print("-- _foto_valid")
        palsu = os.path.join(tmp, "json.jpg")
        with open(palsu, "wb") as f:
            f.write(_amplop(url).ljust(432, b" "))
        h.cek("cache JSON .jpg -> False", _foto_valid(palsu) is False)
        h.cek("cache JSON .jpg ikut dihapus", not os.path.exists(palsu))
        asli = os.path.join(tmp, "asli.jpg")
        with open(asli, "wb") as f:
            f.write(JPEG_PALSU)
        h.cek("JPEG asli -> True dan tetap ada", _foto_valid(asli) and os.path.exists(asli))
        h.cek("file tidak ada -> False", _foto_valid(os.path.join(tmp, "x.jpg")) is False)

        print("-- download_foto vs server tiruan")
        _tes_server_tiruan(h, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"OFFLINE: {h.lolos} lolos, {h.gagal} gagal")
    return h


def _tes_server_tiruan(h, tmp):
    rute = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, ctype, body = rute.get(
                self.path, (404, "application/json", b'{"success":false}'))
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    J, I = "application/json", "image/jpeg"
    rute.update({
        # alur baru normal: amplop -> meternfs -> gambar
        "/meter/ok.jpg": (200, J, _amplop(base + "/meternfs/ok.jpg")),
        "/meternfs/ok.jpg": (200, I, JPEG_PALSU),
        # kondisi server 2026-09-14: amplop ada, meternfs 404
        "/meter/hilang.jpg": (200, J, _amplop(base + "/meternfs/hilang.jpg")),
        "/meternfs/hilang.jpg": (404, J, b'{"code":404,"success":false}'),
        # amplop menunjuk amplop lagi: harus berhenti, bukan berputar
        "/meter/putar.jpg": (200, J, _amplop(base + "/meter/putar2.jpg")),
        "/meter/putar2.jpg": (200, J, _amplop(base + "/meter/putar.jpg")),
        # token ditolak
        "/meter/token.jpg": (401, J, b'{"code":401,"success":false}'),
        # perilaku lama: URL langsung mengirim gambar
        "/meter/langsung.jpg": (200, I, JPEG_PALSU),
        # 200 berlabel gambar tapi isinya JSON
        "/meter/nyamar.jpg": (200, I, b'{"success":true,"data":{}}'),
    })
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    client = SimbaClient(base)
    client.session.trust_env = False    # jangan lewat proxy untuk localhost

    def unduh(nama):
        path = os.path.join(tmp, "dl", nama)
        return client.download_foto(base + "/meter/" + nama, path, timeout=10), path

    def bersih(path):
        return not os.path.exists(path) and not os.path.exists(path + ".part")

    try:
        for nama, label in [("ok.jpg", "amplop -> meternfs -> gambar"),
                            ("langsung.jpg", "URL langsung gambar (lama)")]:
            ok, path = unduh(nama)
            valid = os.path.exists(path) and adalah_gambar(open(path, "rb").read(4))
            h.cek(f"{label}: True + JPEG tersimpan", ok is True and valid, f"ok={ok}")

        for nama, label in [("hilang.jpg", "meternfs 404"),
                            ("putar.jpg", "amplop -> amplop"),
                            ("nyamar.jpg", "200 image/jpeg isi JSON")]:
            ok, path = unduh(nama)
            h.cek(f"{label}: False tanpa file sisa", ok is False and bersih(path), f"ok={ok}")

        try:
            unduh("token.jpg")
            h.cek("401: SimbaAuthError", False, "tidak raise")
        except SimbaAuthError:
            h.cek("401: SimbaAuthError", True)
    finally:
        srv.shutdown()


# =========================
# ONLINE
# =========================

def _get_ulang(session, url, percobaan=3, **kw):
    """GET dengan ulang untuk timeout koneksi (server SIMBA sering ngadat)."""
    galat = None
    for _ in range(percobaan):
        try:
            return session.get(url, timeout=45, **kw), None
        except Exception as e:     # noqa: BLE001 - diagnosis, bukan logika app
            galat = e
            time.sleep(2)
    return None, f"{type(galat).__name__}"


def _siapkan_client(args):
    client = SimbaClient(SIMBA_BASE_URL)
    login_baru = False

    if not args.login:
        try:
            with open(args.token_dari, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError) as e:
            print(f"  (token tidak terbaca dari {args.token_dari}: {e})")
            cfg = {}
        token, user = cfg.get("token"), args.user or cfg.get("transaksi_by")
        if token and user:
            client.username = user
            client.token = token
            client.session.headers["authorization"] = f"Bearer {token}"
            print(f"  memakai token tersimpan untuk {user} (tanpa login baru)")
            return client, login_baru
        print("  token/username tidak lengkap, beralih ke login")

    user = args.user or input("  User SIMBA (mis. 44320.nama): ").strip()
    password = getpass.getpass("  Password: ")
    enkripsi = getpass.getpass("  Kode enkripsi (tokenInfo): ").strip()
    client.login(user, password, enkripsi)
    print(f"  login baru sebagai {user}")
    return client, True


def tes_online(args):
    print("\n=== B. ONLINE (server SIMBA) ===")
    h = Hasil()
    server_gagal = 0
    foto_ok = 0
    s3 = []
    tmp = args.simpan or tempfile.mkdtemp(prefix="tes_foto_online_")
    os.makedirs(tmp, exist_ok=True)

    try:
        client, login_baru = _siapkan_client(args)
    except (SimbaAuthError, SimbaError) as e:
        h.cek("login SIMBA", False, str(e))
        return h, server_gagal, foto_ok

    try:
        urls = []
        for idpel in args.idpel:
            try:
                records = client.get_info_pelanggan(idpel, args.blth)
            except SimbaAuthError as e:
                h.cek(f"infopelanggan {idpel}", False,
                      f"{e} - token ditolak, jalankan ulang dengan --login")
                return h, server_gagal, foto_ok
            except SimbaError as e:
                h.cek(f"infopelanggan {idpel}", False, str(e))
                continue
            dapat = [(idpel, rec.get("blth"), u) for rec in records
                     for item in (rec.get("pathFoto") or []) if isinstance(item, dict)
                     for u in item.values() if u]
            h.cek(f"infopelanggan {idpel}: {len(records)} bulan, {len(dapat)} URL foto",
                  bool(dapat), "tidak ada pathFoto (unit/IDPEL cocok dengan user?)")
            urls += dapat
        urls = urls[:args.maks]

        for n, (idpel, blth, url) in enumerate(urls, 1):
            print(f"\n  [{n}/{len(urls)}] {idpel} blth {blth}  ...{url[-45:]}")

            # diagnosis mentah: langkah mana yang gagal
            r1, err = _get_ulang(client.session, url, headers={"accept": ACCEPT_FOTO})
            langkah2_gambar = None
            if r1 is None:
                print(f"    langkah 1: gagal koneksi ({err})")
            else:
                ctype = r1.headers.get("content-type", "")
                print(f"    langkah 1: HTTP {r1.status_code} {ctype} {len(r1.content)} B")
                try:
                    data = r1.json().get("data") or {}
                except ValueError:
                    data = {}
                storage, url2 = data.get("storage"), data.get("urlPhoto")
                if adalah_gambar(r1.content[:4]):
                    print("    langkah 1 langsung gambar (perilaku lama)")
                    langkah2_gambar = True
                elif url2:
                    print(f"    storage={storage}  urlPhoto=...{url2.split('/photo/')[-1][:50]}")
                    if storage != "NFS":
                        s3.append(storage)
                    r2, err = _get_ulang(client.session, url2, headers={"accept": ACCEPT_FOTO})
                    if r2 is None:
                        print(f"    langkah 2: gagal koneksi ({err})")
                    else:
                        langkah2_gambar = adalah_gambar(r2.content[:4])
                        pesan = "" if langkah2_gambar else f" | {r2.text[:90]}"
                        print(f"    langkah 2: HTTP {r2.status_code} {len(r2.content)} B "
                              f"gambar={langkah2_gambar}{pesan}")

            # fungsi aplikasi yang sebenarnya
            path = os.path.join(tmp, f"{idpel}_{blth}_{n}.jpg")
            try:
                ok = client.download_foto(url, path)
            except SimbaAuthError as e:
                h.cek("download_foto", False, f"SimbaAuthError: {e}")
                continue
            ada = os.path.exists(path)
            valid = ada and adalah_gambar(open(path, "rb").read(4))
            sisa = ada or os.path.exists(path + ".part")

            if ok:
                if h.cek("download_foto -> gambar tersimpan", valid, "True tapi file bukan gambar"):
                    foto_ok += 1
            elif langkah2_gambar:
                h.cek("download_foto", False, "False padahal server mengirim gambar")
            else:
                h.cek("download_foto -> False tanpa file sisa (server tidak kirim foto)",
                      not sisa, "ada file sisa")
                server_gagal += 1

        if s3:
            print(f"\n  CATATAN: storage non-NFS muncul {len(s3)}x ({set(s3)}). Kalau gagal, "
                  "kemungkinan header authorization ikut dikirim ke link S3.")
        if not urls:
            print("  tidak ada URL foto untuk dites")
    finally:
        if login_baru:
            ok, pesan = client.logout()
            print(f"\n  logout: {'berhasil' if ok else 'gagal'} ({pesan})")

    print(f"\n  foto tersimpan di: {tmp}")
    print(f"ONLINE: {h.lolos} lolos, {h.gagal} gagal | foto tersimpan {foto_ok}, "
          f"tidak dikirim server {server_gagal}")
    return h, server_gagal, foto_ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="hanya tes offline")
    ap.add_argument("--idpel", nargs="+", default=IDPEL_DEFAULT)
    ap.add_argument("--blth", default=date.today().strftime("%Y%m"))
    ap.add_argument("--maks", type=int, default=6, help="jumlah foto maksimal")
    ap.add_argument("--token-dari", default=PENGATURAN_OTOMASI,
                    help="pengaturan.json berisi token + transaksi_by")
    ap.add_argument("--user", help="username SIMBA, mis. 44320.nama")
    ap.add_argument("--login", action="store_true",
                    help="login baru (sesi lain di akun ini bisa tertendang)")
    ap.add_argument("--simpan", help="folder simpan foto (default: folder temp)")
    args = ap.parse_args()

    off = tes_offline()
    if args.offline:
        return 0 if off.gagal == 0 else 1

    on, server_gagal, foto_ok = tes_online(args)
    print("\n=== KESIMPULAN ===")
    if off.gagal or on.gagal:
        print("KODE BERMASALAH - lihat baris FAIL di atas")
        return 1
    if foto_ok == 0:
        print("Kode billing v3 benar, tapi server SIMBA tidak mengirim foto "
              "(cek juga di browser: DevTools -> Network -> meternfs)")
        return 2
    if server_gagal:
        print(f"SEBAGIAN: {foto_ok} foto asli terunduh, {server_gagal} tidak dikirim server")
        return 0
    print("SEMUA LOLOS - foto asli berhasil diunduh lewat alur baru")
    return 0


if __name__ == "__main__":
    sys.exit(main())
