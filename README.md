# PLN Billing Analyzer

Aplikasi desktop untuk deteksi anomali tagihan listrik PLN. Membaca data pembacaan meter (file DPM), mendeteksi pola konsumsi abnormal berdasarkan data historis, mengunduh foto meter pelanggan dari portal PLN, dan mengekspor laporan Excel yang dikategorikan dengan foto tersemat.

## Fitur

- **Auto-detect format DPM** — Mendukung format "Resmi" dan "Belum" secara otomatis berdasarkan nama kolom
- **Analisis anomali berlapis** — 10 aturan deteksi: Stand Minus, Stand Tidak Wajar, Meter Macet, Jam Tinggi/Tidak Wajar, Kenaikan, Penurunan, Anomali Daya, Trend Naik, Anomali vs Sejawat
- **Perbandingan historis** — Membandingkan konsumsi dengan rata-rata 6 bulan terakhir dari database
- **Download foto meter** — Mengunduh foto 3 bulan terakhir per pelanggan dari portal PLN secara paralel (25 worker)
- **Laporan Excel lengkap** — Sheet per status, ringkasan, prioritas kelainan, warna gradient, sparkline, dan foto tersemat
- **Modern UI** — Dark/Light mode, drag & drop file, progress step indicator, log berwarna dengan timestamp

## Screenshot Alur Kerja

```
Load Data → Prepare → Analyze → Download Foto → Export Excel
```

## Prasyarat

- **Python 3.8+**
- **Google Chrome** + **ChromeDriver** (untuk login portal PLN)
- **Akses jaringan internal PLN** (portal `portalapp.iconpln.co.id`)

## Instalasi

```bash
git clone https://github.com/USERNAME/billing-analyzer.git
cd billing-analyzer
pip install pandas openpyxl requests selenium tqdm python-dateutil pillow ttkbootstrap tkinterdnd2
```

Letakkan `chromedriver.exe` di folder root project (sejajar dengan `main.py`).

## Struktur Project

```
billing-analyzer/
├── main.py              # Entry point
├── ui.py                # GUI (ttkbootstrap + tkinterdnd2)
├── config.py            # Konfigurasi constants
├── core/
│   ├── __init__.py
│   ├── loader.py        # Load & auto-detect format DPM
│   ├── analyzer.py      # Join DB, hitung derived fields, apply rules
│   ├── photo.py         # Download foto meter (ThreadPoolExecutor)
│   ├── pipeline.py      # Orchestrator & session management
│   └── excel.py         # Export & format Excel dengan foto
├── database.xlsb        # Database historis (127K rows, schema: IDPEL, BULAN, STAND, PEMAKAIAN, DAYA, KEY)
├── dpm/                 # Folder file input DPM
├── foto/                # Folder hasil download foto
└── hasil/               # Folder output Excel
```

> Folder `database.xlsb`, `dpm/`, `foto/`, `hasil/` tidak disertakan di repository.

## Cara Pakai

1. Jalankan aplikasi:
   ```bash
   python main.py
   ```

2. Pilih file DPM (drag & drop atau klik Browse)

3. Pilih periode (Tahun dan Bulan)

4. Klik **Jalankan**

5. Jika cookie portal expired, browser Chrome akan terbuka untuk login:
   - Login ke portal PLN
   - Selesaikan captcha
   - Klik **OK** di dialog aplikasi

6. Tunggu proses hingga selesai — hasil ada di folder `hasil/{BLTH}/`

## Format Input

### Format DPM "Resmi"
Kolom yang diperlukan: `IDPEL`, `SAHLWBP`, `LWBPPAKAI`, `DAYA`, `TARIF`, `KELAINAN_BC_METER`

### Format DPM "Belum"
Kolom yang diperlukan: `IDPEL`, `STAN_METER`, `PEMKWH`, `DAYA`, `TARIF`, `KDBACA`

Kode kelainan otomatis didecode: A=KWH Meter Macet, B=Mundur, C=Tidak Ada, dst.

### Database Historis (`database.xlsb`)
Schema: `IDPEL`, `BULAN`, `STAND`, `PEMAKAIAN`, `DAYA`, `KEY`

## Aturan Deteksi Anomali

Diterapkan secara berurutan (first match wins):

| # | Aturan | Kondisi |
|---|--------|---------|
| 1 | Stand Minus | Stand kini < stand lalu |
| 2 | Stand Tidak Wajar | Selisih stand ≠ pemakaian |
| 3 | Meter Macet | Pemakaian = 0, rata-rata > 0 |
| 4 | Jam Tinggi | Jam nyala 720-744 jam |
| 5 | Jam Tidak Wajar | Jam nyala > 744 jam |
| 6 | Kenaikan | Pemakaian > 150 dan > 1.5x rata-rata |
| 7 | Perlu Perhatian | Pemakaian 1.2-1.5x rata-rata |
| 8 | Trend Naik | Konsisten naik ≥3 bulan, kenaikan >30% |
| 9 | Anomali vs Sejawat | Pemakaian > 3x median sejawat |
| 10 | Penurunan | Pemakaian < 50% rata-rata |
| 11 | Anomali Daya | Pemakaian > 2x daya |

## Output Excel

File hasil dikelompokkan dalam sheet:
- **Sheet per status** — Stand Minus, Meter Macet, Kenaikan, Penurunan, dll.
- **PRIORITAS_KELAINAN** — Pelanggan dengan kelainan meter prioritas tinggi
- **RINGKASAN** — Distribusi status, Top 10 jam nyala, Top 10 kenaikan/penurunan
- **Normal** — Pelanggan tanpa anomali

Setiap sheet dilengkapi warna status, heat map jam nyala, gradient persentase perubahan, sparkline historis, dan foto meter tersemat.

## Autentikasi Portal

Aplikasi menggunakan cookie-based authentication:
1. Mencoba memuat cookie dari `cookie.json`
2. Jika expired, membuka Chrome via Selenium untuk login manual + CAPTCHA
3. Cookie baru disimpan untuk sesi berikutnya

## Teknologi

- **Python** — Bahasa utama
- **Tkinter + ttkbootstrap** — GUI desktop dengan tema Material Design
- **tkinterdnd2** — Drag & drop file
- **pandas** — Pengolahan data
- **openpyxl** — Export & format Excel
- **Selenium** — Login portal PLN
- **requests** — Download foto & API calls
- **ThreadPoolExecutor** — Download paralel (25 workers)

## Konfigurasi

Edit `config.py` untuk mengubah:
- `BASE_URL` — URL portal PLN
- `MAX_WORKERS` — Jumlah thread download foto (default: 25)
- `THEME_DARK` / `THEME_LIGHT` — Tema UI (default: darkly / cosmo)

## Lisensi

Project ini untuk penggunaan internal PLN.
