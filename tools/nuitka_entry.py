"""Entry point khusus build Nuitka (lihat build_nuitka.bat).

Nuitka standalone tidak men-set sys.frozen, sehingga config.py mengira mode
dev: APP_DATA_DIR tidak pernah jatuh ke %LOCALAPPDATA%\\PLN-Billing saat
di-install di Program Files. Set di sini, SEBELUM main/config diimpor, supaya
source aplikasi tidak perlu tahu soal Nuitka. Tanpa sys._MEIPASS, config.py
memakai folder .exe sebagai BUNDLE_DIR - sama seperti onedir PyInstaller.
"""

import sys

sys.frozen = True

import main  # noqa: E402

main.main()
