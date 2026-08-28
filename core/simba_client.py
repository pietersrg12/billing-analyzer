"""
SIMBA API client.

Wraps:
- POST /acmt/v1/auth/login         -> bearer token
- POST /acmt/informasi/infopelanggan -> data + URL foto
- GET <pathFoto URL>               -> binary image
- POST /acmt/laporan/rekapkbtunggal/detail/download/excel
                                   -> .xlsx dalam bungkus JSON base64

Token cached to disk so user only logs in once per session lifetime
(or until token expires).
"""

import base64
import json
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class SimbaAuthError(Exception):
    """Raised when SIMBA returns 401 or login fails."""


class SimbaError(Exception):
    """Generic SIMBA API error."""


class SimbaClient:

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    )

    # Pool & retry config untuk performa download paralel tinggi.
    # urllib3 default pool=10 jadi worker >10 bakal antri di connection pool.
    POOL_CONNECTIONS = 100
    POOL_MAXSIZE = 100

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "accept": "application/json",
            "content-type": "application/json",
            "user-agent": self.USER_AGENT,
        })

        # HTTP adapter dgn connection pool besar + retry untuk 5xx & connection error.
        # Ini yang bikin paralelisasi 25-50 worker beneran efektif.
        retry = Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            pool_connections=self.POOL_CONNECTIONS,
            pool_maxsize=self.POOL_MAXSIZE,
            max_retries=retry,
            pool_block=False,
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.username = None
        self.token = None

    # =========================
    # AUTH
    # =========================

    def login(self, username, password):
        url = f"{self.base_url}/acmt/v1/auth/login"
        payload = {
            "username": username,
            "password": password,
            "tokenInfo": password,
        }

        try:
            resp = self.session.post(url, json=payload, timeout=30)
        except requests.RequestException as e:
            raise SimbaError(f"Tidak bisa terhubung ke SIMBA: {e}")

        if resp.status_code != 200:
            raise SimbaAuthError(
                f"Login gagal (HTTP {resp.status_code}): {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError:
            raise SimbaAuthError("Login response bukan JSON valid")

        if not data.get("success"):
            raise SimbaAuthError(
                f"Login gagal: {data.get('message', 'Unknown error')}"
            )

        token = None
        d = data.get("data")
        if isinstance(d, dict):
            token = d.get("token")
        if not token:
            token = data.get("token")
        if not token and isinstance(d, str):
            token = d

        if not token:
            raise SimbaAuthError("Token tidak ditemukan di response login")

        self.username = username
        self.token = token
        self.session.headers.update({"authorization": f"Bearer {token}"})

    def load_token(self, path):
        """Load saved token. Return True if loaded successfully."""
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            token = data.get("token")
            username = data.get("username")
            if not token or not username:
                return False
            self.token = token
            self.username = username
            self.session.headers.update({"authorization": f"Bearer {token}"})
            return True
        except (OSError, ValueError):
            return False

    def save_token(self, path):
        if not self.token or not self.username:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {"token": self.token, "username": self.username},
                    f,
                )
        except OSError:
            pass

    @property
    def unitup(self):
        if not self.username:
            return None
        # 5 digit pertama sebelum "."
        return self.username.split(".")[0]

    # =========================
    # API
    # =========================

    def probe(self, idpel, blth):
        """Test apakah token masih valid dengan panggil infopelanggan ringan."""
        try:
            self.get_info_pelanggan(idpel, blth, timeout=15)
            return True
        except SimbaAuthError:
            return False
        except SimbaError:
            # Server error / timeout: anggap token mungkin valid, biar
            # error muncul saat run pipeline saja
            return True

    def get_info_pelanggan(self, idpel, blth, timeout=60):
        if not self.unitup:
            raise SimbaError("Belum login ke SIMBA")

        url = f"{self.base_url}/acmt/informasi/infopelanggan"
        payload = {
            "idpel": str(idpel),
            "unitup": self.unitup,
            "blth": str(blth),
            "transaksiby": self.unitup,
        }

        try:
            resp = self.session.post(url, json=payload, timeout=timeout)
        except requests.RequestException as e:
            raise SimbaError(f"Network error: {e}")

        if resp.status_code == 401:
            raise SimbaAuthError("Token expired atau tidak valid")

        if resp.status_code != 200:
            raise SimbaError(
                f"infopelanggan HTTP {resp.status_code}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError:
            raise SimbaError("Response infopelanggan bukan JSON valid")

        if not data.get("success"):
            msg = (data.get("message") or "").lower()
            if "token" in msg or "auth" in msg or "login" in msg:
                raise SimbaAuthError(data.get("message", "Auth error"))
            raise SimbaError(
                f"infopelanggan gagal: {data.get('message', 'Unknown error')}"
            )

        return data.get("data", []) or []

    def download_foto(self, foto_url, save_path, timeout=30):
        # Streaming download: hemat memory + lebih cepat untuk file besar.
        # Pakai chunk write 64KB.
        # Raise SimbaAuthError untuk 401 supaya caller bisa stop early.
        #
        # PENTING: server endpoint /acmt/download/photo/... produce image/jpeg.
        # Default session header `accept: application/json` akan ditolak server
        # dengan HTTP 406 ("The accept header value did not match the value in
        # @Produces"). Jadi override Accept ke image/jpeg untuk request ini.
        headers = {"accept": "image/jpeg, image/*, */*"}
        try:
            with self.session.get(
                foto_url, timeout=timeout, stream=True, headers=headers
            ) as resp:
                if resp.status_code == 401:
                    raise SimbaAuthError("Token expired saat download foto")

                if resp.status_code != 200:
                    return False

                # Validasi minimal length via header kalau ada
                cl = resp.headers.get("content-length")
                if cl and int(cl) < 100:
                    return False

                try:
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    tmp_path = save_path + ".part"
                    total = 0
                    with open(tmp_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                                total += len(chunk)

                    if total < 100:
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                        return False

                    # Atomic rename agar tidak ada file korup
                    os.replace(tmp_path, save_path)
                    return True
                except OSError:
                    return False
        except SimbaAuthError:
            raise
        except requests.RequestException:
            return False

    def download_kode_baca(self, blth, kdbaca, timeout=300):
        """Unduh laporan Detail Kode Baca Tunggal satu kategori. Return bytes .xlsx.

        Beda dari endpoint export lain: server TIDAK mengirim attachment, tapi
        JSON {data: {filename, contentType, base64}} - jadi header default
        session (accept: application/json) memang yang benar di sini, jangan
        di-override seperti download_foto.

        Kategori kdbaca ("NORMAL", "GANGGUAN BACA", "GANGGUAN METER") harus
        ditarik satu per satu; server tidak menyediakan opsi "SEMUA". Ketiganya
        mengembalikan `filename` yang identik, jadi caller yang menyimpan ke
        disk wajib membedakan namanya sendiri.
        """
        if not self.unitup:
            raise SimbaError("Belum login ke SIMBA")

        url = f"{self.base_url}/acmt/laporan/rekapkbtunggal/detail/download/excel"
        payload = {
            "unitup": self.unitup,
            "blth": str(blth),
            "kodeRbm": "",
            "kdbaca": kdbaca,
            # transaksiBy pakai username LENGKAP ("44320.firdaus"), bukan
            # self.unitup - beda dengan infopelanggan yang justru pakai unitup.
            "transaksiBy": self.username,
            "level": "1",
        }

        try:
            resp = self.session.post(url, json=payload, timeout=timeout)
        except requests.RequestException as e:
            raise SimbaError(f"Gagal request kode baca {kdbaca} {blth}: {e}")

        if resp.status_code == 401:
            raise SimbaAuthError("Token expired saat download kode baca")
        if resp.status_code != 200:
            raise SimbaError(
                f"Download kode baca {kdbaca} {blth} gagal "
                f"(HTTP {resp.status_code}): {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError:
            raise SimbaError(f"Response kode baca {kdbaca} {blth} bukan JSON valid")

        if not data.get("success"):
            msg = str(data.get("message", "Unknown error"))
            if any(k in msg.lower() for k in ("token", "auth", "login")):
                raise SimbaAuthError(f"Auth gagal saat download kode baca: {msg}")
            raise SimbaError(f"Download kode baca {kdbaca} {blth} gagal: {msg}")

        b64 = (data.get("data") or {}).get("base64")
        if not b64:
            raise SimbaError(
                f"Response kode baca {kdbaca} {blth} tidak memuat file "
                f"(message: {data.get('message')})"
            )

        try:
            return base64.b64decode(b64)
        except (ValueError, TypeError) as e:
            raise SimbaError(f"Base64 kode baca {kdbaca} {blth} rusak: {e}")

    # =========================
    # HELPERS
    # =========================

    @staticmethod
    def extract_first_foto_url(record):
        """Ekstrak URL foto pertama (photo1) dari record infopelanggan."""
        path_foto = record.get("pathFoto") or []
        for item in path_foto:
            if not isinstance(item, dict):
                continue
            for _, url in item.items():
                if url:
                    return url
        return None
