"""
Jendela login SSO IAM PLN untuk portal billing (newap2t).

Alur portal (dari bundle frontend newap2t, 2026-11):
  1. GET {AUTH}/sso -> URL authorize iam.pln.co.id (redirect_uri dikunci ke
     http://newap2t.pln.co.id/crm/redirect-login).
  2. User login di IAM -> redirect ke .../crm/redirect-login?code=..&session_state=..
  3. POST {AUTH}/sso/exchange {code, session_state, tokenDeviceInfo} -> token.

Karena redirect_uri milik newap2t, aplikasi desktop tidak bisa menerima
redirect sendiri. Jendela WebView2 (pywebview) membuka halaman IAM dan
memantau URL-nya; begitu sampai di redirect-login, `code` diambil dan jendela
ditutup. Halaman redirect-login newap2t hanya menukar kode saat tombol submit
ditekan, jadi kode yang tertangkap masih utuh.

pywebview harus berjalan di main thread, sedangkan main thread aplikasi
dipakai Tk. Maka jendela dijalankan di PROSES ANAK: aplikasi memanggil dirinya
sendiri dengan `--sso-login <url> <file_hasil>` (lihat main.py), lalu membaca
hasilnya dari file sementara. File dipakai, bukan stdout, karena exe di-build
tanpa console sehingga stdout proses anak tidak bisa diandalkan. File itu
dihapus segera setelah dibaca.

Profil WebView2 DISIMPAN di `<APP_DATA_DIR>/sso_webview` (private_mode=False).
Profil kosong tiap kali (private_mode=True, versi pertama) membuat halaman IAM
butuh ~60 s untuk tampil; dengan profil tersimpan 2-7 s (diukur 2026-11-19),
karena cache aset dan cookie IAM ikut terbawa. Risiko lama profil tersimpan -
SPA newap2t yang memegang `user-token` lama langsung pindah halaman - tidak
berlaku lagi karena kode ditangkap dari REQUEST navigasi sebelum SPA jalan;
localStorage newap2t juga dibersihkan setiap kali token diambil darinya.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlparse

PATH_REDIRECT = "/crm/redirect-login"
JUDUL = "Login SSO PLN - Portal Billing"
BATAS_WAKTU = 600  # detik; user bisa menutup jendela kapan saja untuk batal


class SsoError(Exception):
    """Jendela login SSO tidak bisa dijalankan."""


def ambil_kode(url):
    """(code, session_state) dari URL redirect-login, atau None."""
    try:
        u = urlparse(url or "")
    except ValueError:
        return None
    if not u.path.rstrip("/").endswith(PATH_REDIRECT):
        return None
    q = parse_qs(u.query)
    code = (q.get("code") or [""])[0]
    if not code:
        return None
    return code, (q.get("session_state") or [""])[0]


# =========================
# SISI PROSES ANAK
# =========================

def jalankan_jendela(url, file_hasil):
    """Buka jendela IAM, tulis {code, session_state} ke `file_hasil`.

    Return exit code: 0 = kode tertangkap, 1 = ditutup tanpa login,
    2 = pywebview/WebView2 tidak tersedia.
    """
    try:
        import webview
    except Exception as e:  # noqa: BLE001 - apa pun sebabnya, laporkan
        _tulis(file_hasil, {"error": f"pywebview tidak tersedia: {e}"})
        return 2

    hasil = {}
    kunci = threading.Lock()
    tertutup = threading.Event()
    window = webview.create_window(JUDUL, url, width=520, height=720)

    def selesai(data):
        """Simpan hasil pertama saja, lalu tutup jendela."""
        with kunci:
            if hasil:
                return
            hasil.update(data)
            _tulis(file_hasil, hasil)
        try:
            window.destroy()
        except Exception:  # noqa: BLE001 - sudah tertutup
            pass

    # Jalur utama: tangkap REQUEST navigasi ke redirect-login, sebelum halaman
    # AP2T tampil. Tidak bergantung pada event `loaded`: get_current_url()
    # menunggu halaman selesai dimuat maks. 20 s lalu melempar error, dan
    # halaman IAM/OTP/newap2t bisa lebih lambat dari itu (pemantau versi
    # pertama berhenti di situ dan kodenya tidak pernah tertangkap).
    def saat_request(request):
        kode = ambil_kode(getattr(request, "url", ""))
        if kode:
            selesai({"code": kode[0], "session_state": kode[1]})

    window.events.request_sent += saat_request
    window.events.closed += tertutup.set

    def pantau():
        """Cadangan: polling URL, dan kalau SPA AP2T sempat menukar kodenya
        sendiri (user mengisi enkripsi di halaman), ambil token dari
        localStorage-nya. Error apa pun hanya dilewati sampai jendela tutup."""
        while not hasil and not tertutup.is_set():
            try:
                sekarang = window.get_current_url() or ""
                kode = ambil_kode(sekarang)
                if kode:
                    selesai({"code": kode[0], "session_state": kode[1]})
                    return
                if "newap2t.pln.co.id/crm" in sekarang:
                    token = window.evaluate_js("localStorage.getItem('user-token')")
                    if token:
                        akun = window.evaluate_js("localStorage.getItem('account')")
                        # Dibersihkan supaya token ini tidak terbaca lagi
                        # sebagai "baru" pada login berikutnya.
                        window.evaluate_js("localStorage.clear()")
                        selesai({"token": token, "account": akun or ""})
                        return
            except Exception:  # noqa: BLE001 - halaman belum siap; coba lagi
                pass
            tertutup.wait(0.5)

    try:
        webview.start(pantau, private_mode=False, storage_path=_folder_profil())
    except Exception as e:  # noqa: BLE001 - mis. runtime WebView2 tidak ada
        _tulis(file_hasil, {"error": f"Jendela login gagal dibuka: {e}"})
        return 2
    return 0 if hasil else 1


def _folder_profil():
    from config import user_path
    path = user_path("sso_webview")
    os.makedirs(path, exist_ok=True)
    return path


def _tulis(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


# =========================
# SISI APLIKASI
# =========================

def _perintah_diri():
    """Perintah untuk menjalankan aplikasi ini sendiri."""
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return [sys.executable]
    main_py = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"
    )
    return [sys.executable, main_py]


def minta_kode(url, timeout=BATAS_WAKTU):
    """Jalankan jendela SSO dan tunggu. Return dict salah satu dari:
      {"code", "session_state"}  - kode IAM tertangkap (jalur normal), atau
      {"token", "account"}       - SPA AP2T sudah menukar kodenya sendiri,
                                   token diambil dari localStorage-nya;
    atau None kalau user menutup jendela tanpa login. Raise SsoError kalau jendela
    tidak bisa dijalankan sama sekali."""
    fd, file_hasil = tempfile.mkstemp(prefix="sso_", suffix=".json")
    os.close(fd)
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proses = subprocess.run(
                [*_perintah_diri(), "--sso-login", url, file_hasil],
                timeout=timeout,
                creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            raise SsoError(f"Login SSO melewati batas waktu {timeout // 60} menit")
        except OSError as e:
            raise SsoError(f"Jendela login SSO gagal dijalankan: {e}")

        try:
            with open(file_hasil, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}

        if data.get("code"):
            return {"code": data["code"],
                    "session_state": data.get("session_state") or ""}
        if data.get("token"):
            return {"token": data["token"], "account": data.get("account") or ""}
        if data.get("error"):
            raise SsoError(data["error"])
        if proses.returncode not in (0, 1):
            raise SsoError(f"Jendela login SSO berhenti (kode {proses.returncode})")
        return None
    finally:
        try:
            os.remove(file_hasil)
        except OSError:
            pass


def jalankan_dari_argv(argv):
    """Dipanggil main.py untuk `--sso-login <url> <file_hasil>`."""
    i = argv.index("--sso-login")
    if i + 2 >= len(argv):
        return 2
    return jalankan_jendela(argv[i + 1], argv[i + 2])


