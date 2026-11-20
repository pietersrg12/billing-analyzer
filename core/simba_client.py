"""
Client API ACMT (gateway FSM).

Di teks UI/log server ini disebut ACMT - SIMBA sudah menjadi nama aplikasi.
Nama modul, kelas, dan exception tetap `simba` karena riwayat kodenya.

Wraps:
- POST /acmt/v1/auth/login         -> bearer token
- POST /acmt/v1/auth/logout        -> tutup sesi di server
- POST /acmt/informasi/infopelanggan -> data + URL foto
- GET <pathFoto URL>               -> gambar, atau amplop JSON {storage, url|urlPhoto}
- GET <urlPhoto>                   -> binary image (/acmt/download/photo/meternfs/...)
- POST /acmt/laporan/rekapkbtunggal/detail/download/excel
                                   -> .xlsx dalam bungkus JSON base64

Skema request auth diambil dari spesifikasi gateway sendiri
(GET /gateway/openapi/raw, tanpa login).

Setiap sesi = login -> kerja -> logout. Token TIDAK disimpan ke disk: setelah
logout token itu sudah dicabut server, jadi tidak ada yang bisa dipakai ulang.
`tokenInfo` adalah kode enkripsi dari generator milik user yang di-paste di
dialog login (sama seperti portal billing) - tidak bisa diturunkan dari
password.
"""

import base64
import io
import json
import os
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class SimbaAuthError(Exception):
    """Raised when ACMT returns 401 or login fails."""


class SimbaError(Exception):
    """Generic ACMT API error."""


def adalah_gambar(awal):
    """True kalau byte awal file bertanda JPEG atau PNG.

    Server bisa membalas HTTP 200 berisi JSON, jadi tanda tangan file lebih
    andal daripada content-type atau ukuran. Dipakai juga oleh photo.py untuk
    menolak file cache yang bukan gambar.
    """
    return bool(awal) and (awal[:3] == b"\xff\xd8\xff" or awal[:4] == b"\x89PNG")


def _simpan_mentah_kode_baca(isi, blth, kdbaca):
    """Simpan balasan kode baca yang tidak terbaca, untuk diagnosis. Tidak pernah raise."""
    try:
        from config import user_path
        folder = user_path("unduhan")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(
            folder, f"_acmt_gagal_{blth}_{kdbaca.replace(' ', '_')}.bin")
        with open(path, "wb") as f:
            f.write(isi)
        return path
    except Exception as e:
        return f"(gagal disimpan: {e})"


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
        # Disimpan di memori saja, dibutuhkan lagi oleh logout().
        self.token_info = None

    # =========================
    # AUTH
    # =========================

    def login(self, username, password, token_info):
        """Login ACMT. `token_info` = kode enkripsi yang di-paste user."""
        url = f"{self.base_url}/acmt/v1/auth/login"
        payload = {
            "username": username,
            "password": password,
            "tokenInfo": token_info,
        }

        try:
            resp = self.session.post(url, json=payload, timeout=30)
        except requests.RequestException as e:
            raise SimbaError(f"Tidak bisa terhubung ke ACMT: {e}")

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
            # Nama field saja (bukan nilainya) supaya penyebab terlihat tanpa
            # membocorkan isi balasan ke log.
            kunci = sorted(d) if isinstance(d, dict) else type(d).__name__
            raise SimbaAuthError(
                "Token tidak ditemukan di response login "
                f"(message: {data.get('message')!r}, data: {kunci})"
            )

        self.username = username
        self.token = token
        self.token_info = token_info
        self.session.headers.update({"authorization": f"Bearer {token}"})

    def logout(self, timeout=30):
        """Tutup sesi di server. Return (ok, pesan); tidak pernah raise.

        Body-nya memakai `userName` (N besar), BEDA dari login yang `username` -
        persis skema LogoutRequest di /gateway/openapi/raw. Token lokal selalu
        dibuang, berhasil atau tidak, supaya client ini tidak dipakai lagi
        dengan sesi yang mungkin sudah mati.
        """
        if not self.token:
            return True, "tidak ada sesi aktif"

        url = f"{self.base_url}/acmt/v1/auth/logout"
        payload = {
            "userName": self.username,
            "tokenInfo": self.token_info or "",
        }

        try:
            try:
                resp = self.session.post(url, json=payload, timeout=timeout)
            except requests.RequestException as e:
                return False, f"tidak bisa terhubung ke ACMT: {e}"

            try:
                data = resp.json()
            except ValueError:
                data = None

            if isinstance(data, dict):
                pesan = str(data.get("message") or "")
                ok = resp.status_code == 200 and bool(data.get("success"))
            else:
                pesan = (resp.text or "")[:200]
                ok = False

            if not ok:
                pesan = f"HTTP {resp.status_code}: {pesan}"
            return ok, pesan
        finally:
            self.token = None
            self.token_info = None
            self.session.headers.pop("authorization", None)

    @property
    def unitup(self):
        if not self.username:
            return None
        # 5 digit pertama sebelum "."
        return self.username.split(".")[0]

    # =========================
    # API
    # =========================

    def get_info_pelanggan(self, idpel, blth, timeout=60):
        if not self.unitup:
            raise SimbaError("Belum login ke ACMT")

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

    # Amplop JSON yang wajar cuma ratusan byte; di atas ini pasti bukan amplop.
    MAKS_BODY_AMPLOP = 1024 * 1024

    def download_foto(self, foto_url, save_path, timeout=30):
        """Unduh satu foto ke save_path. Return True kalau gambar tersimpan.

        URL `pathFoto` dari infopelanggan (/acmt/download/photo/meter/...)
        bisa membalas gambar langsung, atau amplop JSON yang menunjuk file
        aslinya: sejak 2026-09 {data: {storage: "NFS", urlPhoto: "/meternfs/..."}},
        sejak 2026-10 untuk foto baru {data: {storage: "S3", url: "<presigned>"}}
        (port 8086, X-Amz-Signature, berlaku 30 menit - dikirim TANPA Bearer).
        Amplop diikuti SATU kali: JSON yang menunjuk ke JSON lagi dianggap
        gagal, bukan diputar terus. URL-nya diikuti apa adanya, bukan ditebak,
        karena field `storage` menandakan ada lebih dari satu backend.

        Raise SimbaAuthError untuk 401 supaya caller bisa stop early.
        """
        url = foto_url
        for _ in range(2):
            hasil = self._unduh_atau_arahkan(url, save_path, timeout)
            if not isinstance(hasil, str):
                return hasil
            url = hasil
        return False

    def _unduh_atau_arahkan(self, url, save_path, timeout):
        """Satu GET foto. Return True/False, atau URL tujuan (str) kalau server
        membalas amplop JSON berisi `urlPhoto`."""
        # Default session header `accept: application/json` ditolak endpoint
        # gambar dengan HTTP 406 ("The accept header value did not match the
        # value in @Produces"). `*/*` tetap disertakan supaya amplop JSON dari
        # /photo/meter/ juga diterima.
        headers = {"accept": "image/jpeg, image/*, */*"}
        # urlPhoto lama bisa relatif (/meternfs/...) - lengkapi dengan host ACMT.
        url = urljoin(self.base_url + "/", url)
        # Bearer token HANYA untuk gateway ACMT. URL S3 presigned (port 8086,
        # X-Amz-Signature) sudah membawa auth-nya sendiri di query: kalau
        # Authorization ikut terkirim, S3 menolak (dua mekanisme auth), dan
        # token tidak boleh bocor ke host lain. None = hapus dari header session.
        if not url.startswith(self.base_url + "/"):
            headers["authorization"] = None
        tmp_path = save_path + ".part"
        try:
            with self.session.get(
                url, timeout=timeout, stream=True, headers=headers
            ) as resp:
                if resp.status_code == 401:
                    raise SimbaAuthError("Token expired saat download foto")
                if resp.status_code != 200:
                    return False

                # Streaming 64KB: hemat memori untuk file besar.
                chunks = resp.iter_content(chunk_size=65536)
                awal = b""
                for chunk in chunks:
                    if chunk:
                        awal = chunk
                        break

                ctype = (resp.headers.get("content-type") or "").lower()
                if "json" in ctype or not adalah_gambar(awal):
                    body = awal
                    for chunk in chunks:
                        body += chunk
                        if len(body) > self.MAKS_BODY_AMPLOP:
                            return False
                    return self._url_dari_amplop(body)

                try:
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    total = len(awal)
                    with open(tmp_path, "wb") as f:
                        f.write(awal)
                        for chunk in chunks:
                            if chunk:
                                f.write(chunk)
                                total += len(chunk)
                except (OSError, requests.RequestException):
                    _hapus_diam(tmp_path)
                    return False

                if total < 100:
                    _hapus_diam(tmp_path)
                    return False

                # Atomic rename agar tidak ada file korup
                try:
                    os.replace(tmp_path, save_path)
                except OSError:
                    _hapus_diam(tmp_path)
                    return False
                return True
        except SimbaAuthError:
            raise
        except requests.RequestException:
            return False

    @staticmethod
    def _url_dari_amplop(body):
        """Ambil `data.urlPhoto` dari amplop JSON. False kalau tidak ada."""
        try:
            data = json.loads(body)
        except ValueError:
            return False
        if not isinstance(data, dict):
            return False
        if not data.get("success"):
            msg = str(data.get("message") or "")
            if any(k in msg.lower() for k in ("token", "auth", "login")):
                raise SimbaAuthError(f"Auth gagal saat download foto: {msg}")
            return False
        isi = data.get("data")
        if not isinstance(isi, dict):
            return False
        # Sejak 2026-10 foto baru disimpan di S3 dan amplopnya membawa `url`
        # (presigned, berlaku 30 menit); foto lama di NFS masih `urlPhoto`.
        # Keduanya bisa muncul untuk satu pelanggan (beda bulan).
        url = isi.get("url") or isi.get("urlPhoto")
        return url if isinstance(url, str) and url.strip() else False

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
            raise SimbaError("Belum login ke ACMT")

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
            isi = base64.b64decode(b64)
        except (ValueError, TypeError) as e:
            raise SimbaError(f"Base64 kode baca {kdbaca} {blth} rusak: {e}")

        # .xlsx asli berupa zip ("PK"). Sejak 2026-10 server membungkusnya
        # sebagai wadah OLE2 terenkripsi (EncryptionInfo), dengan PASSWORD =
        # username login ACMT lengkap (mis. "44320.SANTI"). Didekripsi di sini
        # supaya parser di hilir tetap menerima .xlsx biasa tanpa perubahan.
        if isi[:2] != b"PK":
            if isi[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                simpan = _simpan_mentah_kode_baca(isi, blth, kdbaca)
                raise SimbaError(
                    f"Laporan kode baca {kdbaca} {blth} bukan .xlsx maupun OLE2 "
                    f"(awal {isi[:16]!r}, {len(isi):,} byte). Disimpan di {simpan}"
                )
            isi = self._dekripsi_xlsx(isi, blth, kdbaca)
        return isi

    def _dekripsi_xlsx(self, isi, blth, kdbaca):
        """Dekripsi balasan ACMT yang terkunci. Password = username ACMT lengkap."""
        try:
            import msoffcrypto
        except ImportError:
            simpan = _simpan_mentah_kode_baca(isi, blth, kdbaca)
            raise SimbaError(
                "Laporan ACMT terenkripsi tapi 'msoffcrypto-tool' belum "
                "terpasang (pip install msoffcrypto-tool). "
                f"File tersimpan di {simpan}"
            )

        buf = io.BytesIO()
        try:
            kunci = msoffcrypto.OfficeFile(io.BytesIO(isi))
            kunci.load_key(password=self.username)
            kunci.decrypt(buf)
        except Exception as e:
            simpan = _simpan_mentah_kode_baca(isi, blth, kdbaca)
            raise SimbaError(
                f"Laporan kode baca {kdbaca} {blth} terenkripsi dan gagal "
                f"didekripsi dengan username ACMT: {e}. Disimpan di {simpan}"
            )

        hasil = buf.getvalue()
        if hasil[:2] != b"PK":
            simpan = _simpan_mentah_kode_baca(isi, blth, kdbaca)
            raise SimbaError(
                f"Hasil dekripsi kode baca {kdbaca} {blth} bukan .xlsx. "
                f"Disimpan di {simpan}"
            )
        return hasil

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


def _hapus_diam(path):
    try:
        os.remove(path)
    except OSError:
        pass
