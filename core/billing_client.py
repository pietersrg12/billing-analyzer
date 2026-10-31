"""
Client portal billing PLN (host 10.68.35.109) - sumber `database.xlsb`.

Sistem ini TERPISAH dari SIMBA/ACMT (core/simba_client.py): host beda, token
beda, dan skema login-nya beda. Dua port dipakai:

- POST {AUTH}/auth/login-v2
      -> bearer token + kode unit (unitupi/unitap/unitup)
- POST {API}/api/monitoring/billing/monitoring-billing-detail-export
- POST {API}/api/monitoring/billing/monitoring-dlpd-detail-export
- POST {API}/api/monitoring-dpm-detail/export
      -> file .xlsx mentah (binary stream, bukan JSON)
  Tiap export punya endpoint list pasangannya yang mengembalikan
  `totalItems`, dipakai untuk mengisi `size` payload export.

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
        # Pool di-set eksplisit (default requests cuma 10) karena DLPD & DPM
        # bisa ditarik bersamaan lewat 2 thread pada session yang sama.
        adapter = HTTPAdapter(
            pool_connections=10, pool_maxsize=10, pool_block=False,
            max_retries=retry,
        )
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

        Token portal billing membawa klaim `exp`, jadi kedaluwarsa bisa dibaca
        langsung dari JWT-nya tanpa request - penting karena update database
        jalan tanpa file DPM dimuat, jadi tidak ada IDPEL untuk di-probe.
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

    # Endpoint list dipakai untuk mengambil totalItems sebelum export: payload
    # export menuntut `size` eksplisit, dan menebak angka besar berisiko ditolak
    # server sekaligus menyembunyikan kalau ternyata datanya lebih banyak.
    URL_LIST_BILLING = "/api/monitoring/billing/monitoring-billing-detil"
    URL_LIST_DLPD = "/api/monitoring/billing/monitoring-billing-dlpd-detil"
    URL_LIST_DPM = "/api/monitoring-dpm-detil"

    # Payload list = payload export dikurangi kunci-kunci ini (dibandingkan
    # langsung dari capture ketiga pasangan endpoint).
    KUNCI_KHUSUS_EXPORT = ("tipe", "dlpdKvarh")

    URL_EXPORT_BILLING = "/api/monitoring/billing/monitoring-billing-detail-export"
    URL_EXPORT_DLPD = "/api/monitoring/billing/monitoring-dlpd-detail-export"
    URL_EXPORT_DPM = "/api/monitoring-dpm-detail/export"

    def kode_proses(self, kode_list):
        """['T0','T1'] -> ['44BIMT0','44BIMT1'] memakai unitap hasil login.

        Kode disimpan tanpa prefix unit supaya setelan yang sama bisa dipakai
        unit mana pun; prefix-nya baru ditempel di sini.
        """
        if not self.unitap:
            raise BillingAuthError("Belum login ke portal billing")
        return [f"{self.unitap}{str(k).strip().upper()}" for k in kode_list]

    def _payload_unit(self, thblrek):
        """Bagian payload yang sama di semua endpoint monitoring."""
        return {
            "thblrek": str(thblrek),
            "unitap": self.unitap,
            "unitup": self.unitup,
            "unitupi": self.unitupi,
        }

    def hitung_total(self, path_list, payload, timeout=120):
        """Jumlah baris (`totalItems`) untuk satu kombinasi filter.

        Return None kalau tidak terbaca - caller memakai angka cadangan supaya
        satu endpoint hitung yang rewel tidak menggagalkan seluruh unduhan.
        """
        if not self.token:
            raise BillingAuthError("Belum login ke portal billing")

        payload = dict(payload)
        payload["page"] = 0
        payload["size"] = 1
        # Kunci khusus export dibuang: browser tidak pernah mengirimnya ke
        # endpoint list, dan sebagian backend menolak field asing.
        for k in self.KUNCI_KHUSUS_EXPORT:
            payload.pop(k, None)

        try:
            resp = self.session.post(
                f"{self.api_url}{path_list}", json=payload, timeout=timeout
            )
        except requests.RequestException:
            return None

        if resp.status_code == 401:
            raise BillingAuthError("Token billing kedaluwarsa (HTTP 401)")
        if resp.status_code != 200:
            # Kegagalan auth harus naik ke atas, bukan jadi None: kalau ditelan,
            # unduhan lanjut memakai size cadangan lalu gagal lagi di export
            # dengan sebab yang sama.
            pesan = _pesan_respons(resp)
            if _pesan_auth(pesan):
                raise BillingAuthError(f"{pesan} (HTTP {resp.status_code})")
            return None

        try:
            data = (resp.json().get("data") or {}).get("totalItems")
        except ValueError:
            return None

        try:
            total = int(data)
        except (TypeError, ValueError):
            return None
        return total if total > 0 else None

    def _unduh_export(self, path_export, payload, save_path, label, timeout=600):
        """POST export lalu simpan .xlsx biner ke save_path. Return jumlah byte."""
        if not self.token:
            raise BillingAuthError("Belum login ke portal billing")

        # Header default session `accept: application/json` ditolak endpoint
        # yang menghasilkan attachment (pola yang sama bikin download foto kena
        # HTTP 406 di simba_client). Minta apa saja.
        headers = {"accept": "*/*"}

        try:
            resp = self.session.post(
                f"{self.api_url}{path_export}", json=payload,
                headers=headers, stream=True, timeout=timeout,
            )
        except requests.RequestException as e:
            raise BillingError(f"Gagal request {label}: {e}")

        if resp.status_code == 401:
            raise BillingAuthError("Token billing kedaluwarsa (HTTP 401)")
        if resp.status_code != 200:
            pesan = _pesan_respons(resp)
            if _pesan_auth(pesan):
                raise BillingAuthError(f"{pesan} (HTTP {resp.status_code})")
            raise BillingError(f"{label} gagal (HTTP {resp.status_code}): {pesan}")

        # Server bisa balas 200 dengan JSON error alih-alih file.
        ctype = (resp.headers.get("content-type") or "").lower()
        if "json" in ctype:
            pesan = _pesan_respons(resp)
            if _pesan_auth(pesan):
                raise BillingAuthError(pesan)
            raise BillingError(f"{label} tidak menghasilkan file: {pesan}")

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
            raise BillingError(f"Gagal menulis file {label}: {e}")

        # File xlsx terkecil sekalipun jauh di atas 1 KB; di bawah itu pasti
        # bukan workbook (biasanya body error yang lolos cek content-type).
        if total < 1024:
            _silent_remove(tmp_path)
            raise BillingError(f"{label} balas file kosong ({total} byte)")

        os.replace(tmp_path, save_path)
        return total

    def _unduh_dengan_catat(self, path_list, path_export, payload, save_path,
                            label, timeout, catat):
        """hitung_total + _unduh_export, mencatat durasi tiap bagian kalau diminta.

        Dipisah supaya ketiga download method memakai pola & log yang sama,
        dan supaya porsi preflight-count vs generate-di-server kelihatan.
        """
        t0 = time.perf_counter()
        total = self.hitung_total(path_list, payload)
        t_count = time.perf_counter() - t0
        if total:
            payload["size"] = total

        t1 = time.perf_counter()
        n = self._unduh_export(path_export, payload, save_path, label, timeout)
        t_export = time.perf_counter() - t1

        if catat:
            catat(f"    ({label}: hitung-total {t_count:.1f}s + "
                  f"generate+unduh {t_export:.1f}s = {t_count + t_export:.1f}s)")
        return n

    def download_billing_detail(self, thblrek, save_path, size, timeout=600,
                                catat=None):
        """Unduh Monitoring_Billing_Detail satu periode (sumber database rekening)."""
        payload = self._payload_unit(thblrek)
        payload.update({
            "page": 0,
            "size": int(size),
            "idpel": "",
            "postingbilling": "SEMUA",
            "kdProsesKlp": ["SEMUA"],
            "tipe": "excel",
        })
        return self._unduh_dengan_catat(
            self.URL_LIST_BILLING, self.URL_EXPORT_BILLING, payload, save_path,
            f"export billing {thblrek}", timeout, catat,
        )

    def download_dlpd_detail(self, thblrek, kode_list, save_path,
                             dlpd="SEMUA", status_verifikasi="BELUM",
                             size=None, timeout=600, catat=None):
        """Unduh Monitoring_Dlpd_Detail - file input utama aplikasi."""
        payload = self._payload_unit(thblrek)
        payload.update({
            # `page` di endpoint ini bertipe STRING, sedangkan di DPM integer.
            # Ditiru apa adanya dari capture; jangan diseragamkan tanpa diuji.
            "page": "0",
            "size": int(size) if size else 1,
            "dlpd": dlpd,
            "kdProsesKlp": self.kode_proses(kode_list),
            "idpel": "",
            "statusVerifikasiDlpd": status_verifikasi,
            "dlpdKvarh": None,
            "tipe": "excel",
            "dlpdPlts": None,
        })
        label = f"export DLPD {thblrek}"
        t_count = 0.0
        if not size:
            t0 = time.perf_counter()
            total = self.hitung_total(self.URL_LIST_DLPD, payload)
            t_count = time.perf_counter() - t0
            payload["size"] = total or 100000
        t1 = time.perf_counter()
        n = self._unduh_export(self.URL_EXPORT_DLPD, payload, save_path,
                               label, timeout)
        t_export = time.perf_counter() - t1
        if catat:
            catat(f"    ({label}: hitung-total {t_count:.1f}s + "
                  f"generate+unduh {t_export:.1f}s = {t_count + t_export:.1f}s)")
        return n

    def download_dpm_detail(self, thblrek, kode_list, save_path,
                            kodeposting="SUDAH", size=None, timeout=600,
                            catat=None):
        """Unduh Monitoring_DPM_Detail - dipakai hanya untuk kelainan_bc_meter."""
        payload = self._payload_unit(thblrek)
        payload.update({
            "page": 0,
            "size": int(size) if size else 1,
            "kodeposting": kodeposting,
            "kdProsesKlp": self.kode_proses(kode_list),
            "idpel": "",
            "tipe": "excel",
        })
        label = f"export DPM {thblrek}"
        t_count = 0.0
        if not size:
            t0 = time.perf_counter()
            total = self.hitung_total(self.URL_LIST_DPM, payload)
            t_count = time.perf_counter() - t0
            payload["size"] = total or 100000
        t1 = time.perf_counter()
        n = self._unduh_export(self.URL_EXPORT_DPM, payload, save_path,
                               label, timeout)
        t_export = time.perf_counter() - t1
        if catat:
            catat(f"    ({label}: hitung-total {t_count:.1f}s + "
                  f"generate+unduh {t_export:.1f}s = {t_count + t_export:.1f}s)")
        return n


# =========================
# HELPERS
# =========================

# Portal ini menolak token basi dengan HTTP 500 + {"message": "Token tidak
# sesuai"}, BUKAN 401. Mengandalkan kode status saja membuat kegagalan auth
# terbaca sebagai error server biasa, sehingga user tidak pernah diminta login
# ulang dan unduhannya mentok terus.
PETUNJUK_AUTH = ("token", "auth", "login", "unauthor", "kedaluwarsa", "expired")


def _pesan_auth(teks):
    """True kalau body respons berbau masalah token/otentikasi."""
    if not teks:
        return False
    rendah = str(teks).lower()
    return any(k in rendah for k in PETUNJUK_AUTH)


def _pesan_respons(resp):
    """Ambil `message` dari body JSON; kalau bukan JSON, potongan teks mentah."""
    try:
        data = resp.json()
    except ValueError:
        return (resp.text or "")[:200]
    if isinstance(data, dict):
        return str(data.get("message") or data.get("error") or "")[:200]
    return str(data)[:200]


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
