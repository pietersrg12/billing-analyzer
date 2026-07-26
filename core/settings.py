"""
Rule settings (threshold deteksi anomali) — bisa diubah lewat UI.

Semua nilai di sini persis meniru konstanta yang sebelumnya hardcode di
core/analyzer.py. Disimpan sebagai JSON di RULE_SETTINGS_FILE (folder data
user) supaya tetap ada lintas sesi, dengan fallback otomatis ke default kalau
file belum ada / rusak / ada key yang hilang (misal setelah update aplikasi
menambah rule baru).
"""

import json
import os

from config import RULE_SETTINGS_FILE

DEFAULT_RULES = {
    "jumlah_bulan_rata2": 6,
    "jam_nyala_tinggi_min": 720,
    "jam_nyala_tidak_wajar_min": 744,
    "stand_p1_jam_konstan": 718,
    "kenaikan_pemakaian_min": 150,
    "kenaikan_multiplier": 1.5,
    "kenaikan_tambahan": 50,
    "perlu_perhatian_ratio_min": 1.2,
    "perlu_perhatian_ratio_max": 1.5,
    "perlu_perhatian_pemakaian_min": 100,
    "penurunan_ratio_max": 0.5,
    "anomali_daya_multiplier": 2,
    "trend_min_bulan": 3,
    "trend_growth_ratio": 1.3,
    "stand_tidak_wajar_toleransi": 1,
    "stan_baca_flat_toleransi": 0,
    "stan_baca_flat_min_bulan": 3,
    "stan_baca_placeholder_max": 1,
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
