"""
Alur koreksi: Load, Simulasi, Kirim, verifikasi, jurnal, dan laporan. Tanpa UI.

Baris berupa dict yang diisi bertahap, bukan DataFrame, karena tiap baris berubah
satu per satu selagi UI menampilkannya. Kolom TAHAP menyimpan posisinya; semua
langkah melewati baris yang tahapnya sudah lewat, sehingga aman diulang utuh oleh
`_kerja_billing` setelah login ulang di tengah batch.

Pengaman kirim, yang mana pun tidak boleh dilonggarkan tanpa alasan kuat:
- POST sekali per baris, tidak pernah diulang otomatis.
- Baris diproses paralel per IDPEL, tetapi satu IDPEL hanya dipegang satu pekerja
  dan selalu diselesaikan utuh, termasuk verifikasi dan jurnalnya.
- Niat kirim ditulis ke jurnal SEBELUM POST, supaya aplikasi yang mati di tengah
  kiriman tetap meninggalkan jejak baris yang statusnya tidak pasti.
- Data server dibaca ulang tepat sebelum POST.
"""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from config import (
    BILLING_API_URL,
    BILLING_AUTH_URL,
    BILLING_TOKEN_FILE,
    ENABLE_KOREKSI_KIRIM,
    HASIL_DIR,
    KOREKSI_LOG_DIR,
    KOREKSI_PEKERJA,
    KOREKSI_PEKERJA_KIRIM,
)
from core.billing_client import BillingAuthError, BillingClient
from core.koreksi_client import (
    KoreksiClient,
    KoreksiError,
    KoreksiJaringan,
    KoreksiTidakPasti,
    identitas_token,
    nilai_uraian,
    payload_kirim,
    payload_simulasi,
)
from core.koreksi_sumber import (
    BATAS_JAM_NYALA_720,
    JALUR_720,
    JALUR_BILLING,
)
from core.pipeline import _get_billing_client, _kerja_billing, _stempel_waktu

TAHAP_BELUM = ""
TAHAP_LOADED = "LOADED"
TAHAP_SIMULASI = "SIMULASI"
TAHAP_DIBLOKIR = "DIBLOKIR"
TAHAP_SUDAH = "SUDAH TERKOREKSI"
TAHAP_GAGAL = "GAGAL"
TAHAP_BERUBAH = "DATA BERUBAH"
TAHAP_OK = "BERHASIL"
TAHAP_BELUM_VERIFIKASI = "TERKIRIM, BELUM TERVERIFIKASI"
TAHAP_TIDAK_PASTI = "TIDAK PASTI"

PERINGATAN_MERAH = "merah"
PERINGATAN_KUNING = "kuning"

# Hasil jurnal yang berarti koreksi mungkin sudah masuk ke server.
HASIL_NIAT = "NIAT"
HASIL_DITOLAK_TOKEN = "TOKEN DITOLAK"
TAHAP_TERKIRIM = (TAHAP_OK, TAHAP_BELUM_VERIFIKASI, TAHAP_TIDAK_PASTI)
# Sudah dicoba kirim tapi hasilnya belum diketahui; harus dibaca dari server dulu.
TAHAP_PERLU_CEK = (TAHAP_BELUM_VERIFIKASI, TAHAP_TIDAK_PASTI)
HASIL_TERKIRIM = (HASIL_NIAT,) + TAHAP_TERKIRIM

# Berhenti sebelum batch habis kalau jaringan jelas sedang bermasalah.
BATAS_GAGAL_BERUNTUN = 3

KOLOM_REGISTER_LAIN = (
    "wbpLalu", "wbpAkhir", "kvarhLalu", "kvarhAkhir", "kvamaxAkhir", "kvawbpAkhir",
)
KOLOM_PENENTU_DATA = (
    "lwbpLalu", "lwbpAkhir", "tglBacaLalu", "tglBacaAkhir", "jamNyala",
)


class KoreksiBerhenti(Exception):
    """Batch dihentikan otomatis. Pesannya ditampilkan ke operator."""


class Jurnal:
    """Catatan append-only per unit + bulan. Tidak pernah memuat token."""

    def __init__(self, unitup, thblrek, folder=None):
        self.folder = os.path.join(folder or KOREKSI_LOG_DIR, str(unitup), str(thblrek))
        self.path = os.path.join(self.folder, f"jurnal_{thblrek}.jsonl")
        self._terakhir = {}
        self._kunci = threading.Lock()
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                for baris in f:
                    try:
                        catatan = json.loads(baris)
                    except ValueError:
                        continue  # baris terpotong saat aplikasi mati
                    self._terakhir[catatan.get("idpel")] = catatan

    def catat(self, baris, hasil, user_id, pesan=""):
        catatan = {
            "waktu": datetime.now().isoformat(timespec="seconds"),
            "idpel": baris["IDPEL"],
            "jenis": baris["JENIS"],
            "stan": int(baris["STAN_BARU"]),
            "alasan": baris["ALASAN"],
            "user_id": user_id,
            "hasil": hasil,
            "pesan": pesan,
        }
        with self._kunci:
            os.makedirs(self.folder, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(catatan, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._terakhir[catatan["idpel"]] = catatan

    def terakhir(self, idpel):
        with self._kunci:
            return self._terakhir.get(idpel)


def siapkan_baris(df):
    """DataFrame `baca_koreksi` menjadi list dict dengan kolom status kosong."""
    rows = []
    for r in df.to_dict("records"):
        r["STAN_BARU"] = None if pd.isna(r["STAN_BARU"]) else int(r["STAN_BARU"])
        r["STAN_BARU_TEKS"] = "" if r["STAN_BARU"] is None else str(r["STAN_BARU"])
        rows.append(r)
    reset_server(rows)
    return rows


def _kosongkan(r):
    r.update({
        "TAHAP": TAHAP_BELUM,
        "CENTANG": False,
        "PELANGGAN": None,
        "NAMA": "",
        "JN_SERVER": None,
        "JN_HASIL": None,
        "RPTAG_LAMA": None,
        "RPTAG_BARU": None,
        "SELISIH": None,
        "PERINGATAN": "",
        "BLOKIR": [],
        "CATATAN": [r["PERHATIAN"]] if r.get("PERHATIAN") else [],
        "JURNAL_SAAT_MUAT": None,
        "PERNAH_KIRIM": False,
    })


def reset_server(rows):
    """Buang semua hasil server dari baris yang belum pernah dikirim."""
    for r in rows:
        if r.get("TAHAP") not in TAHAP_TERKIRIM:
            _kosongkan(r)


def siapkan_ulang(rows):
    """Siapkan baris gagal untuk diulang; baris yang sudah beres tidak disentuh.

    Gagal saat simulasi cukup mengulang simulasi karena data pelanggannya sudah
    ada. DATA BERUBAH harus dimuat lagi karena data simpanannya sudah basi.
    """
    for r in rows:
        if r["TAHAP"] == TAHAP_GAGAL and r["PELANGGAN"]:
            r["TAHAP"] = TAHAP_LOADED
            r["BLOKIR"] = []
        elif r["TAHAP"] in (TAHAP_GAGAL, TAHAP_BERUBAH):
            _kosongkan(r)


def jumlah_belum_selesai(rows):
    """Baris yang masih perlu diproses oleh tombol Load & Simulasi."""
    return sum(
        1 for r in rows
        if r["JALUR"] and r["TAHAP"] in (
            TAHAP_BELUM, TAHAP_LOADED, TAHAP_GAGAL, TAHAP_BERUBAH,
        ) + TAHAP_PERLU_CEK
    )


def bisa_dikirim(baris):
    """Baris boleh dicentang: sudah disimulasikan dan tidak diblokir."""
    return baris["TAHAP"] == TAHAP_SIMULASI


def aman_dicentang(baris):
    """True kalau baris dicentang otomatis.

    Keputusan operator: catatan seperti ACMT baca ulang atau stand server berbeda
    hanya informasi. Yang menahan hanya JN hasil yang >= 720 atau tidak terbaca,
    dan baris yang pernah dikirim (pengaman kirim ganda).
    """
    return not baris["PERINGATAN"] and not baris["PERNAH_KIRIM"]


def keterangan(baris):
    """Teks alasan lengkap satu baris, untuk tabel dan laporan."""
    bagian = []
    if baris["MASALAH"]:
        bagian.append(baris["MASALAH"])
    bagian.extend(baris["BLOKIR"])
    bagian.extend(baris["CATATAN"])
    return "; ".join(bagian)


def _sama(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def _ada_nilai(nilai):
    return nilai not in (None, "", 0, 0.0)


def periksa_server(baris, data, thblrek, unitup):
    """(blokir, catatan) dari data server untuk satu baris. Fungsi murni."""
    blokir = []
    catatan = []
    stan = baris["STAN_BARU"]

    if str(data.get("thblrek")) != str(thblrek):
        blokir.append(f"Periode server {data.get('thblrek')}, bukan {thblrek}")
    if str(data.get("unitup")) != str(unitup):
        blokir.append(f"Pelanggan milik unit {data.get('unitup')}, login unit {unitup}")

    jam = data.get("jamNyala")
    if not isinstance(jam, (int, float)):
        blokir.append("Jam nyala server tidak terbaca")
    else:
        jalur_server = JALUR_720 if jam >= BATAS_JAM_NYALA_720 else JALUR_BILLING
        if jalur_server != baris["JALUR"]:
            blokir.append(
                f"Jam nyala server {jam:g} tidak sesuai jalur {baris['JALUR']}, "
                "kemungkinan data sudah berubah sejak file dibuat"
            )

    lalu = data.get("lwbpLalu")
    if isinstance(lalu, (int, float)) and stan < lalu:
        blokir.append(f"STAN BARU di bawah stand lalu server ({lalu:g})")
    register = [k for k in KOLOM_REGISTER_LAIN if _ada_nilai(data.get(k))]
    if register:
        blokir.append(
            "Pelanggan punya register WBP/kVARh/kVAmaks, koreksi lewat portal"
        )

    acmt = data.get("dataAcmt")
    if isinstance(acmt, dict) and acmt.get("keterangan"):
        catatan.append(f"ACMT: {acmt['keterangan']}")
    if _ada_nilai(data.get("flagCabutPasang")) and not baris["PERHATIAN"]:
        catatan.append("Server menandai pelanggan ini cabut/pasang")
    if baris["STAND_KINI"] is not None and not _sama(
        data.get("lwbpAkhir"), baris["STAND_KINI"]
    ):
        catatan.append(
            f"Stand server {data.get('lwbpAkhir')} berbeda dari file "
            f"({baris['STAND_KINI']:g})"
        )
    return blokir, catatan


def nilai_simulasi(baris, data):
    """Isi kolom hasil simulasi dan tandai peringatan JN hasil. Fungsi murni."""
    jam_hasil = nilai_uraian(data, "JAMNYALA")
    rptag = nilai_uraian(data, "RPTAG")
    baris["JN_HASIL"] = jam_hasil
    baris["RPTAG_BARU"] = rptag
    if isinstance(rptag, (int, float)) and isinstance(baris["RPTAG_LAMA"], (int, float)):
        baris["SELISIH"] = rptag - baris["RPTAG_LAMA"]

    baris["PERINGATAN"] = ""
    if not isinstance(jam_hasil, (int, float)):
        baris["PERINGATAN"] = PERINGATAN_KUNING
        baris["CATATAN"].append("JN hasil tidak tersedia")
    elif jam_hasil >= BATAS_JAM_NYALA_720:
        baris["PERINGATAN"] = PERINGATAN_MERAH
        baris["CATATAN"].append(f"JN hasil masih ≥ 720 ({jam_hasil:g})")
    for pesan in data.get("messages") or []:
        baris["CATATAN"].append(f"Server: {pesan}")

    baris["TAHAP"] = TAHAP_SIMULASI
    baris["CENTANG"] = aman_dicentang(baris)


def _riwayat_koreksi(data):
    """Jumlah koreksi tercatat. lwbpAkhir saja tidak cukup: stand yang sudah
    terkoreksi sebelumnya bisa sama dengan stan baru."""
    return sum(1 for h in data.get("dataBillHistoList") or [] if h.get("tglKoreksi"))


def _data_berubah(lama, baru):
    return _riwayat_koreksi(lama) != _riwayat_koreksi(baru) or any(
        lama.get(k) != baru.get(k) for k in KOLOM_PENENTU_DATA
    )


class Kabar:
    """Penerus progres ke UI lewat `progress_callback`."""

    def __init__(self, progress_callback):
        self.kirim = progress_callback

    def log(self, pesan):
        self.kirim(("koreksi_log", pesan))

    def baris(self, baris):
        self.kirim(("koreksi_baris", baris))

    def progres(self, selesai, total, teks):
        self.kirim(("koreksi_progres", (selesai, total, teks)))

    def akun(self, client):
        self.kirim(("koreksi_akun", {**client.identitas, "unitup": client.unitup}))


def _paralel(target, jumlah_pekerja, kerja_satu, judul, kabar, stop_flag):
    """Jalankan `kerja_satu(baris)` per IDPEL dengan beberapa pekerja.

    `kerja_satu` mengembalikan True kalau gagal karena jaringan. Setelah perintah
    berhenti, baris baru tidak dimulai, tetapi pekerja aktif menyelesaikan barisnya.
    Keluar dari blok `with` menunggu semua pekerja, jadi `_kerja_billing` tidak
    pernah login ulang selagi ada pekerja yang masih memakai token lama.

    Hitungan gagal ada di dalam pekerja, bukan di loop `as_completed`: loop itu
    tertinggal dari antrean, sehingga satu POST lagi sempat dimulai setelah batas
    tercapai, bahkan dengan satu pekerja.
    """
    batal = threading.Event()
    kunci = threading.Lock()
    status = {"beruntun": 0, "putus": False}

    def tugas(baris):
        if batal.is_set() or stop_flag():
            return None
        try:
            gagal_jaringan = kerja_satu(baris)
        except Exception:
            batal.set()
            raise
        with kunci:
            status["beruntun"] = status["beruntun"] + 1 if gagal_jaringan else 0
            if status["beruntun"] >= BATAS_GAGAL_BERUNTUN:
                status["putus"] = True
                batal.set()
        return gagal_jaringan

    galat = None
    selesai = 0
    with ThreadPoolExecutor(max_workers=max(jumlah_pekerja, 1)) as pool:
        per_future = {pool.submit(tugas, baris): baris for baris in target}
        for future in as_completed(per_future):
            try:
                if future.result() is None:
                    continue
            except BillingAuthError as e:
                galat = e  # menang atas galat lain: login ulang bisa melanjutkan
                continue
            except Exception as e:
                galat = galat or e
                continue
            selesai += 1
            kabar.baris(per_future[future])
            kabar.progres(selesai, len(target), f"{judul} {selesai}/{len(target)}")
    if galat:
        raise galat
    if status["putus"]:
        raise KoreksiBerhenti(
            f"Dihentikan otomatis setelah {BATAS_GAGAL_BERUNTUN} kegagalan jaringan "
            "beruntun. Periksa jaringan lalu lanjutkan."
        )
    if stop_flag():
        kabar.log(f"{judul} dihentikan operator")


def _jalur_lain(jalur):
    return JALUR_BILLING if jalur == JALUR_720 else JALUR_720


def _ambil_data(baris, thblrek, client):
    """Data pelanggan dari jalur baris, lalu jalur satunya kalau ditolak.

    Server menolak endpoint yang tidak sesuai jam nyalanya ("Silahkan menggunakan
    fitur Koreksi Billing"). Itu wajar untuk pelanggan yang sudah dikoreksi sejak
    file dibuat, dan statusnya tetap perlu terbaca lewat endpoint yang benar.
    """
    try:
        return client.ambil(baris["JALUR"], baris["IDPEL"], thblrek)
    except KoreksiJaringan:
        raise
    except KoreksiError:
        return client.ambil(_jalur_lain(baris["JALUR"]), baris["IDPEL"], thblrek)


def _muat_satu(baris, thblrek, client, jurnal):
    """Ambil data server satu baris dan cek silang."""
    data = _ambil_data(baris, thblrek, client)
    baris["PELANGGAN"] = data
    baris["NAMA"] = data.get("nama") or ""
    baris["JN_SERVER"] = data.get("jamNyala")
    baris["RPTAG_LAMA"] = nilai_uraian(data, "RPTAG")
    baris["JURNAL_SAAT_MUAT"] = jurnal.terakhir(baris["IDPEL"])

    blokir, catatan = periksa_server(baris, data, thblrek, client.unitup)
    baris["CATATAN"].extend(catatan)
    catatan_jurnal = baris["JURNAL_SAAT_MUAT"]
    terkoreksi = _riwayat_koreksi(data) > 0
    # Dicek paling awal: baris yang sudah terkoreksi memang tidak lagi cocok
    # dengan jalur di file, dan itu bukan masalah.
    if _sama(data.get("lwbpAkhir"), baris["STAN_BARU"]) and terkoreksi:
        baris["TAHAP"] = TAHAP_SUDAH
        baris["CATATAN"].append("Stand server sudah sama dengan STAN BARU")
    elif blokir:
        baris["BLOKIR"] = blokir
        baris["TAHAP"] = TAHAP_DIBLOKIR
    else:
        baris["TAHAP"] = TAHAP_LOADED
        if catatan_jurnal and catatan_jurnal["hasil"] in HASIL_TERKIRIM:
            baris["PERNAH_KIRIM"] = True
            baris["CATATAN"].append(
                f"Pernah dikirim {catatan_jurnal['waktu']} "
                f"({catatan_jurnal['hasil']}), periksa sebelum mengirim lagi"
            )


def _simulasi_satu(baris, client):
    """Simulasi satu baris. Tidak mengubah data billing."""
    payload = payload_simulasi(
        client.user_id, baris["PELANGGAN"], baris["STAN_BARU"],
        baris["ALASAN"], baris["JALUR"],
    )
    nilai_simulasi(baris, client.simulasi(payload))


def _periksa_ulang(baris, thblrek, client, jurnal):
    """Pastikan baris Tidak Pasti dari server, tanpa POST.

    Kalau koreksinya belum masuk, baris dimuat dan disimulasikan seperti baru.
    Jurnal membuatnya tidak tercentang otomatis, jadi kirim ulang tetap keputusan
    operator: POST yang timeout bisa saja masih diproses server.
    """
    data = _ambil_data(baris, thblrek, client)
    if _sudah_masuk(baris, data):
        baris["CATATAN"] = ["Dipastikan sudah masuk ke server"]
        _tandai(baris, TAHAP_OK, jurnal, client)
    else:
        _kosongkan(baris)


def _proses_satu(baris, thblrek, client, jurnal):
    """Load lalu langsung Simulasi satu IDPEL. True kalau gagal karena jaringan.

    Baris gagal Simulasi berstatus LOADED saat diulang, jadi Load-nya dilewati.
    """
    try:
        if baris["TAHAP"] in TAHAP_PERLU_CEK:
            _periksa_ulang(baris, thblrek, client, jurnal)
        if baris["TAHAP"] == TAHAP_BELUM:
            _muat_satu(baris, thblrek, client, jurnal)
        if baris["TAHAP"] == TAHAP_LOADED:
            _simulasi_satu(baris, client)
    except KoreksiError as e:
        # Tetap tidak pasti: kalau menjadi GAGAL, baris bisa dikirim ulang padahal
        # server belum terbaca.
        if baris["TAHAP"] not in TAHAP_PERLU_CEK:
            baris["BLOKIR"] = [f"Simulasi gagal: {e}" if baris["PELANGGAN"] else str(e)]
            baris["TAHAP"] = TAHAP_GAGAL
        return isinstance(e, KoreksiJaringan)
    return False


def proses(rows, thblrek, client, jurnal, kabar, stop_flag):
    """Langkah Load & Simulasi, paralel per IDPEL."""
    target = [
        r for r in rows
        if r["JALUR"] and r["TAHAP"] in (TAHAP_BELUM, TAHAP_LOADED) + TAHAP_PERLU_CEK
    ]
    _paralel(
        target, KOREKSI_PEKERJA,
        lambda baris: _proses_satu(baris, thblrek, client, jurnal),
        "Load & Simulasi", kabar, stop_flag,
    )


def _sudah_masuk(baris, data):
    """True kalau data server menunjukkan koreksi baris ini sudah diterima."""
    return _sama(data.get("lwbpAkhir"), baris["STAN_BARU"]) or (
        _riwayat_koreksi(data) > _riwayat_koreksi(baris["PELANGGAN"])
    )


def _terverifikasi(baris, thblrek, client):
    """True kalau server sudah memuat stan baru. Hanya membaca.

    Jalur lain ikut dicoba karena koreksi bisa memindahkan jam nyala pelanggan
    keluar dari wilayah endpoint semula.

    BillingAuthError sengaja berhenti di sini. Kalau naik ke `_kerja_billing`,
    baris yang POST-nya sudah terkirim ikut diulang dan terkirim dua kali.
    """
    for jalur in (baris["JALUR"], _jalur_lain(baris["JALUR"])):
        try:
            data = client.ambil(jalur, baris["IDPEL"], thblrek)
        except BillingAuthError:
            return False
        except KoreksiError:
            continue
        return _sudah_masuk(baris, data)
    return False


def _tandai(baris, tahap, jurnal, client, pesan=""):
    """Tahap akhir satu baris; hasilnya selalu tercatat di jurnal."""
    baris["TAHAP"] = tahap
    baris["CENTANG"] = False
    if pesan:
        baris["CATATAN"].append(pesan)
    jurnal.catat(baris, tahap, client.user_id, pesan)
    baris["JURNAL_SAAT_MUAT"] = jurnal.terakhir(baris["IDPEL"])


def _kirim_satu(baris, thblrek, client, jurnal, kabar):
    """Kirim satu IDPEL dari cek jurnal sampai verifikasi.

    Return True kalau gagal karena jaringan. BillingAuthError hanya boleh keluar
    selama POST belum diterima server, supaya baris aman diulang setelah login.
    """
    idpel = baris["IDPEL"]
    if jurnal.terakhir(idpel) != baris["JURNAL_SAAT_MUAT"]:
        baris["TAHAP"] = TAHAP_BERUBAH
        baris["CENTANG"] = False
        baris["CATATAN"].append("Jurnal berubah sejak Load, jalankan Load lagi")
        return False

    try:
        terkini = client.ambil(baris["JALUR"], idpel, thblrek)
    except KoreksiError as e:
        baris["TAHAP"] = TAHAP_GAGAL
        baris["CENTANG"] = False
        baris["BLOKIR"] = [f"Tidak terkirim: {e}"]
        return isinstance(e, KoreksiJaringan)
    if _data_berubah(baris["PELANGGAN"], terkini):
        baris["TAHAP"] = TAHAP_BERUBAH
        baris["CENTANG"] = False
        baris["CATATAN"].append("Data server berubah sejak simulasi, tidak dikirim")
        return False

    payload = payload_kirim(
        client.user_id, terkini, baris["STAN_BARU"], baris["ALASAN"],
        baris["JALUR"], baris["KATEGORI"],
    )
    jurnal.catat(baris, HASIL_NIAT, client.user_id)
    baris["JURNAL_SAAT_MUAT"] = jurnal.terakhir(idpel)
    kabar.log(f"Kirim {baris['JENIS']} {idpel} stan {baris['STAN_BARU']}")
    try:
        client.kirim(baris["JALUR"], payload)
    except BillingAuthError:
        # Ditolak sebelum diproses: baris tetap SIMULASI supaya terkirim saat
        # `_kerja_billing` mengulang dengan token baru.
        jurnal.catat(baris, HASIL_DITOLAK_TOKEN, client.user_id)
        baris["JURNAL_SAAT_MUAT"] = jurnal.terakhir(idpel)
        raise
    except KoreksiError as e:
        _tandai(baris, TAHAP_GAGAL, jurnal, client, f"Ditolak server: {e}")
        return False
    except KoreksiTidakPasti as e:
        if _terverifikasi(baris, thblrek, client):
            _tandai(baris, TAHAP_OK, jurnal, client)
            return False
        _tandai(
            baris, TAHAP_TIDAK_PASTI, jurnal, client,
            f"{e}. Tekan Ulangi untuk memeriksa ke server",
        )
        return True

    tahap = TAHAP_OK if _terverifikasi(baris, thblrek, client) else TAHAP_BELUM_VERIFIKASI
    _tandai(baris, tahap, jurnal, client)
    return False


def kirim(rows, thblrek, client, jurnal, kabar, stop_flag):
    """Langkah Kirim, paralel per IDPEL, untuk baris yang dicentang."""
    if not ENABLE_KOREKSI_KIRIM:
        raise KoreksiBerhenti("Kirim koreksi belum diaktifkan.")
    target = [r for r in rows if r["CENTANG"] and bisa_dikirim(r)]
    _paralel(
        target, KOREKSI_PEKERJA_KIRIM,
        lambda baris: _kirim_satu(baris, thblrek, client, jurnal, kabar),
        "Kirim", kabar, stop_flag,
    )


def ringkasan(rows):
    """{tahap: jumlah} untuk baris yang masuk jalur koreksi."""
    hitung = {}
    for r in rows:
        if r["JALUR"]:
            tahap = r["TAHAP"] or "BELUM DIPROSES"
            hitung[tahap] = hitung.get(tahap, 0) + 1
    return hitung


def tulis_laporan(rows, thblrek, unitup, identitas):
    """Laporan Excel hasil kiriman. Return path file."""
    folder = os.path.join(HASIL_DIR, str(thblrek))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"Koreksi_{unitup}_{thblrek}_{_stempel_waktu()}.xlsx")

    rincian = pd.DataFrame([{
        "IDPEL": r["IDPEL"],
        "NAMA": r["NAMA"],
        "JENIS": r["JENIS"],
        "PILIHAN": r["PILIHAN"],
        "JAM NYALA": r["JAM_NYALA"],
        "JN HASIL": r["JN_HASIL"],
        "STAND LALU": r["STAND_LALU"],
        "STAND KINI": r["STAND_KINI"],
        "STAN BARU": r["STAN_BARU"],
        "RPTAG LAMA": r["RPTAG_LAMA"],
        "RPTAG BARU": r["RPTAG_BARU"],
        "SELISIH": r["SELISIH"],
        "ALASAN": r["ALASAN"],
        "STATUS": r["TAHAP"] or "BELUM DIPROSES",
        "KETERANGAN": keterangan(r),
    } for r in rows if r["JALUR"] or r["MASALAH"]])

    kepala = [
        ("Unit", unitup),
        ("BLTH", thblrek),
        ("Akun", f"{identitas.get('nama') or '-'} ({identitas.get('userId') or '-'})"),
        ("Waktu", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    kepala += sorted(ringkasan(rows).items())
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(kepala, columns=["KETERANGAN", "NILAI"]).to_excel(
            writer, sheet_name="RINGKASAN", index=False)
        rincian.to_excel(writer, sheet_name="RINCIAN", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            for kolom in ws.columns:
                lebar = max(len(str(c.value or "")) for c in kolom)
                ws.column_dimensions[kolom[0].column_letter].width = min(lebar + 2, 50)
    return path


def _jalankan(tugas, thblrek, progress_callback, stop_flag, login_event,
              credentials_holder):
    """Bungkus satu langkah dengan login portal yang sama seperti Unduh DLPD."""
    kabar = Kabar(progress_callback)

    def kerja(billing):
        client = KoreksiClient(billing)
        kabar.akun(client)
        tugas(client, Jurnal(client.unitup, thblrek), kabar, stop_flag)
        return client

    def teruskan(pesan):
        if pesan[0] == "log":
            kabar.log(pesan[1])
        else:
            progress_callback(pesan)

    return _kerja_billing(kerja, teruskan, login_event, credentials_holder)


def run_proses(rows, thblrek, **kwargs):
    """Hanya baris yang belum beres yang diproses, jadi menekan tombolnya lagi
    mengulang yang gagal saja."""
    siapkan_ulang(rows)
    return _jalankan(
        lambda client, jurnal, kabar, stop: proses(
            rows, thblrek, client, jurnal, kabar, stop),
        thblrek, **kwargs,
    )


def run_kirim(rows, thblrek, **kwargs):
    return _jalankan(
        lambda client, jurnal, kabar, stop: kirim(
            rows, thblrek, client, jurnal, kabar, stop),
        thblrek, **kwargs,
    )


def run_ganti_akun(progress_callback, login_event, credentials_holder):
    """Login ulang tanpa memakai token tersimpan."""
    kabar = Kabar(progress_callback)

    def teruskan(pesan):
        if pesan[0] == "log":
            kabar.log(pesan[1])
        else:
            progress_callback(pesan)

    billing = _get_billing_client(
        teruskan, login_event, credentials_holder, paksa_login=True,
    )
    kabar.akun(KoreksiClient(billing))


def akun_tersimpan():
    """Identitas token tersimpan tanpa request. None kalau belum ada."""
    billing = BillingClient(BILLING_AUTH_URL, BILLING_API_URL)
    if not billing.load_token(BILLING_TOKEN_FILE) or not billing.probe():
        return None
    return {**identitas_token(billing.token), "unitup": billing.unitup}
