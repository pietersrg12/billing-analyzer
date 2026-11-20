"""
Client endpoint koreksi AP2T, memakai token login portal billing.

Endpoint dan payload mengikuti capture browser (`koreksi billing/api_client.py`):

  GET  /api/data-koreksi-billing-720?idpel=&thblrek=   data pelanggan jalur 720
  GET  /api/data-koreksi-billing?idpel=&thblrek=       data pelanggan jalur billing
  POST /api/simulasi/koreksi                           simulasi, kedua jalur
  POST /api/koreksi-billing/720                        koreksi 720 (kategori)
  POST /api/koreksi-billing/stand-meter                koreksi billing

Session POST sengaja tanpa retry. BillingClient mengulang POST saat 5xx, yang
aman untuk unduhan tetapi bisa mengirim koreksi dua kali ke billing produksi.
"""

import json

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import KOREKSI_ORIGIN
from core.billing_client import (  # noqa: F401  identitas_token di-re-export
    BillingAuthError, _pesan_auth, identitas_token,
)
from core.koreksi_sumber import JALUR_720, JALUR_BILLING

PATH_DATA = {
    JALUR_720: "/api/data-koreksi-billing-720",
    JALUR_BILLING: "/api/data-koreksi-billing",
}
PATH_SIMULASI = "/api/simulasi/koreksi"
PATH_KIRIM = {
    JALUR_720: "/api/koreksi-billing/720",
    JALUR_BILLING: "/api/koreksi-billing/stand-meter",
}

TIMEOUT = 30
# Timeout POST koreksi membuat status baris tidak pasti, jadi tunggunya lebih
# panjang: di kiriman nyata 202611 ada POST yang makan lebih dari 30 detik.
TIMEOUT_KIRIM = 90

# Kolom *Export dari capture; selalu 0 untuk pelanggan biasa.
KOLOM_EXPORT = (
    "slalwbpExport", "slawbpExport", "slakvarhExport", "sahlwbpExport",
    "sahwbpExport", "sahkvarhExport", "slalwbpPasangExp", "sahlwbpCabutExp",
    "slawbpPasangExp", "sahwbpCabutExp", "slakvarhPasangExp", "sahkvarhCabutExp",
)


class KoreksiError(Exception):
    """Request gagal dan pasti tidak mengubah data di server."""


class KoreksiJaringan(KoreksiError):
    """Portal tidak terjangkau. Dipisah dari penolakan server karena hanya ini
    yang menandakan batch perlu dihentikan."""


class KoreksiTidakPasti(Exception):
    """POST gagal tanpa jawaban jelas: koreksinya mungkin sudah masuk."""


def _sesi(retry=None):
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry or 0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class KoreksiClient:

    def __init__(self, billing):
        self.api_url = billing.api_url
        self.token = billing.token
        self.unitup = billing.unitup
        self.identitas = identitas_token(billing.token)
        self.user_id = self.identitas.get("userId")
        if not self.user_id:
            raise BillingAuthError("Token tidak memuat userId; login ulang.")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": KOREKSI_ORIGIN,
            "Referer": f"{KOREKSI_ORIGIN}/",
            "User-Agent": billing.USER_AGENT,
            "Authorization": f"Bearer {billing.token}",
        }
        self._baca = _sesi(Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=(502, 503, 504),
            allowed_methods=("GET",),
            raise_on_status=False,
        ))
        self._tulis = _sesi()

    @staticmethod
    def _isi(resp):
        """Body JSON. Token mati dikenali dari isinya: portal menjawab HTTP 500
        "Token tidak sesuai", bukan 401."""
        try:
            isi = resp.json()
        except ValueError:
            isi = {"message": (resp.text or "")[:300]}
        if not isinstance(isi, dict):
            isi = {"message": str(isi)[:300]}
        pesan = str(isi.get("message") or f"HTTP {resp.status_code}")
        isi["message"] = pesan
        if resp.status_code in (401, 403) or (
            resp.status_code >= 400 and _pesan_auth(pesan)
        ):
            raise BillingAuthError(f"Token ditolak server: {pesan}")
        return isi

    def ambil(self, jalur, idpel, thblrek):
        """GET data pelanggan. Return dict `data`, atau raise KoreksiError."""
        try:
            resp = self._baca.get(
                f"{self.api_url}{PATH_DATA[jalur]}",
                params={"idpel": str(idpel), "thblrek": str(thblrek)},
                headers=self.headers,
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            raise KoreksiJaringan(f"Tidak bisa menghubungi portal: {e}")
        isi = self._isi(resp)
        data = isi.get("data")
        if resp.status_code != 200 or not isi.get("success") or not isinstance(data, dict):
            raise KoreksiError(isi["message"])
        return data

    def simulasi(self, payload):
        """POST simulasi. Return dict `data`. Tidak mengubah data billing."""
        try:
            resp = self._tulis.post(
                f"{self.api_url}{PATH_SIMULASI}",
                data=json.dumps(payload),
                headers=self.headers,
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            raise KoreksiJaringan(f"Tidak bisa menghubungi portal: {e}")
        isi = self._isi(resp)
        data = isi.get("data")
        if resp.status_code != 200 or not isi.get("success") or not isinstance(data, dict):
            raise KoreksiError(isi["message"])
        return data

    def kirim(self, jalur, payload):
        """POST koreksi SEKALI. Sukses return None.

        KoreksiError = server jelas menolak, data tidak berubah.
        KoreksiTidakPasti = tidak ada jawaban jelas; pemanggil wajib membaca
        ulang data server dan tidak boleh mengirim ulang otomatis.
        """
        try:
            resp = self._tulis.post(
                f"{self.api_url}{PATH_KIRIM[jalur]}",
                data=json.dumps(payload),
                headers=self.headers,
                timeout=TIMEOUT_KIRIM,
            )
        except requests.RequestException as e:
            raise KoreksiTidakPasti(f"Tidak ada jawaban dari portal: {e}")
        isi = self._isi(resp)
        if resp.status_code >= 500:
            raise KoreksiTidakPasti(isi["message"])
        if resp.status_code != 200 or not isi.get("success"):
            raise KoreksiError(isi["message"])


def _angka_atau_asli(nilai):
    """5134.0 menjadi 5134 seperti capture browser; yang lain dibiarkan."""
    if isinstance(nilai, float) and nilai.is_integer():
        return int(nilai)
    return nilai


def _payload_dasar(user_id, pelanggan, stan, alasan):
    p = pelanggan
    return {
        "userId": user_id,
        "idpel": str(p.get("idpel", "")),
        "thblrek": str(p.get("thblrek", "")),
        "tglBacaLalu": p.get("tglBacaLalu"),
        "tglBacaAkhir": p.get("tglBacaAkhir"),
        "lwbpLalu": _angka_atau_asli(p.get("lwbpLalu")),
        "lwbpAkhir": str(stan),
        "wbpLalu": _angka_atau_asli(p.get("wbpLalu")),
        "wbpAkhir": None,
        "kvarhLalu": _angka_atau_asli(p.get("kvarhLalu")),
        "kvarhAkhir": None,
        "kvamaxAkhir": None,
        "kvawbpAkhir": None,
        "sahlwbpCabut": p.get("sahlwbpCabut"),
        "slalwbpPasang": p.get("slalwbpPasang"),
        "sahwbpCabut": p.get("sahwbpCabut"),
        "slawbpPasang": p.get("slawbpPasang"),
        "slakvarhPasang": p.get("slakvarhPasang"),
        "sahkvarhCabut": p.get("sahkvarhCabut"),
        "alasan": alasan,
    }


def payload_kirim(user_id, pelanggan, stan, alasan, jalur, kategori):
    payload = _payload_dasar(user_id, pelanggan, stan, alasan)
    if jalur == JALUR_720:
        payload["kategori"] = kategori
    return payload


def payload_simulasi(user_id, pelanggan, stan, alasan, jalur):
    payload = _payload_dasar(user_id, pelanggan, stan, alasan)
    payload.update({kolom: 0 for kolom in KOLOM_EXPORT})
    payload["sumber"] = jalur
    return payload


def nilai_uraian(data, kunci):
    """Nilai satu `uraian` dari data simulasi atau data pelanggan."""
    for nama in ("uraian", "uraianNilaiList"):
        for u in (data or {}).get(nama) or []:
            if isinstance(u, dict) and str(u.get("uraian")).upper() == kunci:
                return u.get("nilai")
    return None
