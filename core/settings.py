"""
Rule settings (threshold deteksi anomali) dan setelan unduhan — bisa
diubah lewat UI.

Semua nilai di sini persis meniru konstanta yang sebelumnya hardcode di
core/analyzer.py. Disimpan sebagai JSON di RULE_SETTINGS_FILE (folder data
user) supaya tetap ada lintas sesi, dengan fallback otomatis ke default kalau
file belum ada / rusak / ada key yang hilang (misal setelah update aplikasi
menambah rule baru).
"""

import json
import os

from config import RULE_SETTINGS_FILE, UNDUH_SETTINGS_FILE

# NOTE: setelan perbandingan pemakaian disimpan sebagai PERSEN, bukan pengali
# (2026-08). Key-nya sengaja diganti nama saat konversi - kalau nama lama
# dipertahankan, rule_settings.json lama yang berisi 1.5 akan terbaca sebagai
# "1,5%" dan diam-diam mengubah hasil deteksi. Dengan nama baru, key lama
# otomatis diabaikan load_rules() dan default baru yang dipakai.
DEFAULT_RULES = {
    "jumlah_bulan_rata2": 6,
    "jam_nyala_tinggi_min": 720,
    "stand_p1_jam_konstan": 718,
    "kenaikan_pemakaian_min": 150,
    "kenaikan_persen_min": 50,      # dulu kenaikan_multiplier 1.5
    "penurunan_persen_min": 50,     # dulu penurunan_ratio_max 0.5
    "trend_min_bulan": 3,
    "trend_persen_min": 30,         # dulu trend_growth_ratio 1.3
    "stand_tidak_wajar_toleransi": 1,
    "cabut_pasang_toleransi": 1,
}


def load_rules():
    """Baca rule settings dari disk, merge di atas default.

    Toleran terhadap file tidak ada / JSON rusak / key hilang atau asing.
    """
    rules = DEFAULT_RULES.copy()

    if not os.path.exists(RULE_SETTINGS_FILE):
        return rules

    try:
        with open(RULE_SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return rules

    if isinstance(saved, dict):
        for key in DEFAULT_RULES:
            if key in saved:
                rules[key] = saved[key]

    return rules


def save_rules(rules):
    """Simpan rule settings ke disk. Hanya key yang dikenal yang disimpan."""
    to_save = {key: rules[key] for key in DEFAULT_RULES if key in rules}
    os.makedirs(os.path.dirname(RULE_SETTINGS_FILE), exist_ok=True)
    with open(RULE_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(to_save, f, indent=2)


def reset_rules():
    """Hapus file settings tersimpan, kembali ke default. Return default."""
    if os.path.exists(RULE_SETTINGS_FILE):
        try:
            os.remove(RULE_SETTINGS_FILE)
        except OSError:
            pass
    return DEFAULT_RULES.copy()


# =========================
# SETELAN UNDUHAN DLPD
# =========================
# Disimpan TERPISAH dari DEFAULT_RULES, bukan digabung. Dialog Pengaturan Rule
# memanggil float() atas setiap key-nya dan ui_dialogs.RULE_FIELD_GROUPS wajib sinkron
# persis dengan DEFAULT_RULES - satu key bertipe list di sana langsung bikin
# dialognya gagal dibuka.
#
# kd_proses_* menyimpan KODE-nya saja (T0, G1, ...), bukan bentuk lengkap
# "44BIMT0". Kode lengkap disusun saat request sebagai unitap + kode, dan
# unitap datang dari response login - jadi setelan yang sama otomatis benar
# di unit mana pun.
DEFAULT_UNDUH = {
    "kd_proses_tersedia": ["T0", "T1", "T2", "T3", "T4", "T5",
                           "G0", "G1", "PJ", "AP", "KI"],
    "kd_proses_dipilih": ["T0", "T1", "T2"],
    "dlpd": "SEMUA",
    "status_verifikasi_dlpd": "BELUM",
    "kodeposting_dpm": "SUDAH",
}


def load_unduh_settings():
    """Baca setelan unduhan dari disk, merge di atas default."""
    setelan = {k: (list(v) if isinstance(v, list) else v)
               for k, v in DEFAULT_UNDUH.items()}

    if not os.path.exists(UNDUH_SETTINGS_FILE):
        return setelan

    try:
        with open(UNDUH_SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return setelan

    if not isinstance(saved, dict):
        return setelan

    for key, default in DEFAULT_UNDUH.items():
        if key not in saved:
            continue
        nilai = saved[key]
        # Tipe yang tidak cocok diabaikan, bukan dipaksa: file rusak/hasil edit
        # tangan tidak boleh menjatuhkan aplikasi saat dialog dibuka.
        if isinstance(default, list):
            if isinstance(nilai, list):
                setelan[key] = [str(x).strip().upper() for x in nilai if str(x).strip()]
        elif isinstance(nilai, str):
            setelan[key] = nilai

    # Pilihan yang kodenya sudah dihapus dari daftar tersedia ikut dibuang,
    # supaya tidak diam-diam terkirim ke server sebagai kode yang tak dikenal.
    tersedia = set(setelan["kd_proses_tersedia"])
    setelan["kd_proses_dipilih"] = [
        k for k in setelan["kd_proses_dipilih"] if k in tersedia
    ]

    return setelan


def save_unduh_settings(setelan):
    """Simpan setelan unduhan. Hanya key yang dikenal yang ditulis."""
    to_save = {k: setelan[k] for k in DEFAULT_UNDUH if k in setelan}
    os.makedirs(os.path.dirname(UNDUH_SETTINGS_FILE), exist_ok=True)
    with open(UNDUH_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(to_save, f, indent=2)
