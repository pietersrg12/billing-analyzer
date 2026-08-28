"""
Client portal billing PLN (host 10.68.35.109) - sumber `database.xlsb`.

Sistem ini TERPISAH dari SIMBA/ACMT (core/simba_client.py): host beda, token
beda, dan skema login-nya beda. Dua port dipakai:

- POST {AUTH}/auth/login-v2
      -> bearer token + kode unit (unitupi/unitap/unitup)
- POST {API}/api/monitoring/billing/monitoring-billing-detail-export
      -> file .xlsx mentah (binary stream, bukan JSON)

Soal `tokenInfo`: portal ini menuntut blob base64 384 byte yang dibuat
generator milik masing-masing user. Blob itu TIDAK bisa dihitung dari
username/password saja, jadi aplikasi hanya meneruskan apa yang di-paste user
di dialog login. Password plaintext tetap ikut dikirim - persis seperti yang
dilakukan portal web-nya, jadi `tokenInfo` berfungsi sebagai amplop
anti-replay, bukan penyembunyi password.
"""

import base64
import json
import os
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class BillingAuthError(Exception):
    """Login gagal, token kedaluwarsa, atau server balas 401."""


class BillingError(Exception):
    """Error umum portal billing."""


class BillingClient:

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    )

    def __init__(self, auth_url, api_url):
        self.auth_url = auth_url.rstrip("/")
        self.api_url = api_url.rstrip("/")

        self.session = requests.Session()
        self.session.headers.update({
            "accept": "application/json",
            "content-type": "application/json",
            "user-agent": self.USER_AGENT,
        })

        retry = Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.username = None
        self.token = None
        self.nama = None
        # Tiga kode unit ini wajib ada di payload export dan datangnya dari
        # response login - user tidak perlu mengetiknya.
        self.unitupi = None
        self.unitap = None
        self.unitup = None

    # =========================
    # AUTH
    # =========================

    def login(self, username, password, token_info):
        """Login ke portal billing. `token_info` = kode enkripsi dari user."""
        url = f"{self.auth_url}/auth/login-v2"
        payload = {
            "username": username,
            "password": password,
            "tokenInfo": token_info,
        }

        try:
            resp = self.session.post(url, json=payload, timeout=60)
        except requests.RequestException as e:
            raise BillingError(f"Tidak bisa terhubung ke portal billing: {e}")

        if resp.status_code != 200:
            raise BillingAuthError(
                f"Login billing gagal (HTTP {resp.status_code}): {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError:
            raise BillingAuthError("Response login billing bukan JSON valid")

        if not data.get("success"):
            raise BillingAuthError(
                f"Login billing gagal: {data.get('message', 'Unknown error')}"
            )

        d = data.get("data") or {}
        token = d.get("token") or data.get("token")
        if not token:
            raise BillingAuthError("Token tidak ditemukan di response login billing")

        self.username = username
        self.token = token
        self.nama = d.get("nama")
        self.unitupi = d.get("unitupi")
        self.unitap = d.get("unitap")
        self.unitup = d.get("unitup") or d.get("unit")

        if not (self.unitupi and self.unitap and self.unitup):
            raise BillingAuthError(
                "Response login tidak memuat kode unit (unitupi/unitap/unitup); "
                "export tidak bisa dijalankan."
            )

        self.session.headers.update({"authorization": f"Bearer {token}"})

    def load_token(self, path):
        """Muat token tersimpan. Return True kalau berhasil."""
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False

        token = data.get("token")
        username = data.get("username")
        unitup = data.get("unitup")
        unitap = data.get("unitap")
        unitupi = data.get("unitupi")
        # Tanpa kode unit lengkap, token saja tidak cukup untuk export.
        if not (token and username and unitup and unitap and unitupi):
            return False

        self.token = token
        self.username = username
        self.unitup = unitup
        self.unitap = unitap
        self.unitupi = unitupi
        self.nama = data.get("nama")
        self.session.headers.update({"authorization": f"Bearer {token}"})
        return True

    def save_token(self, path):
        if not self.token or not self.username:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "token": self.token,
                        "username": self.username,
                        "nama": self.nama,
                        "unitupi": self.unitupi,
                        "unitap": self.unitap,
                        "unitup": self.unitup,
                    },
                    f,
                )
        except OSError:
            pass

    def probe(self):
        """Cek validitas token TANPA request jaringan.

        Beda dari SimbaClient.probe() yang harus memanggil infopelanggan pakai
        satu IDPEL: token portal billing membawa klaim `exp`, jadi kedaluwarsa
        bisa dibaca langsung dari JWT-nya. Ini penting karena update database
        jalan tanpa file DPM dimuat - tidak ada IDPEL untuk di-probe.
        """
        if not self.token:
            return False
        exp = _jwt_exp(self.token)
        if exp is None:
            # Tidak terbaca: anggap valid, biar 401 dari request asli yang
            # memutuskan. Lebih baik daripada memaksa login ulang percuma.
            return True
        return exp > time.time() + 60

    # =========================
    # EXPORT
    # =========================

    def download_billing_detail(self, thblrek, save_path, size, timeout=600):
        """Unduh Monitoring_Billing_Detail satu periode ke `save_path`.

        Response-nya binary .xlsx (~5 MB), bukan JSON.
        """
        if not self.token:
            raise BillingAuthError("Belum login ke portal billing")

        url = f"{self.api_url}/api/monitoring/billing/monitoring-billing-detail-export"
        payload = {
            "page": 0,
            "size": int(size),
            "thblrek": str(thblrek),
            "unitap": self.unitap,
            "unitup": self.unitup,
            "unitupi": self.unitupi,
            "idpel": "",
            "postingbilling": "SEMUA",
            "kdProsesKlp": ["SEMUA"],
            "tipe": "excel",
        }
        # Header default session `accept: application/json` ditolak endpoint
        # yang menghasilkan attachment (pola yang sama bikin download foto
        # kena HTTP 406 di simba_client). Minta apa saja.
        headers = {"accept": "*/*"}

        try:
            resp = self.session.post(
                url, json=payload, headers=headers, stream=True, timeout=timeout
            )
        except requests.RequestException as e:
            raise BillingError(f"Gagal request export billing {thblrek}: {e}")

        if resp.status_code == 401:
            raise BillingAuthError("Token billing kedaluwarsa (HTTP 401)")
        if resp.status_code != 200:
            raise BillingError(
                f"Export billing {thblrek} gagal (HTTP {resp.status_code}): "
                f"{resp.text[:200]}"
            )

        # Server bisa balas 200 dengan JSON error alih-alih file.
        ctype = (resp.headers.get("content-type") or "").lower()
        if "json" in ctype:
            try:
                msg = resp.json().get("message", resp.text[:200])
            except ValueError:
                msg = resp.text[:200]
            raise BillingError(
                f"Export billing {thblrek} tidak menghasilkan file: {msg}"
            )

        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        tmp_path = save_path + ".part"
        total = 0
        try:
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
        except OSError as e:
            _silent_remove(tmp_path)
            raise BillingError(f"Gagal menulis file export {thblrek}: {e}")

        # File xlsx terkecil sekalipun jauh di atas 1 KB; di bawah itu pasti
        # bukan workbook (biasanya body error yang lolos cek content-type).
        if total < 1024:
            _silent_remove(tmp_path)
            raise BillingError(
                f"Export billing {thblrek} balas file kosong ({total} byte)"
            )

        os.replace(tmp_path, save_path)
        return total


# =========================
# HELPERS
# =========================

def _jwt_exp(token):
    """Ambil klaim `exp` dari JWT tanpa verifikasi tanda tangan.

    Cuma dipakai untuk menghindari request yang sudah pasti gagal; keputusan
    otentikasi sebenarnya tetap ada di server.
    """
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = claims.get("exp")
        return float(exp) if exp is not None else None
    except (IndexError, ValueError, TypeError):
        return None


def _silent_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
