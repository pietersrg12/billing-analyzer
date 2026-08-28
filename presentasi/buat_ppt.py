# -*- coding: utf-8 -*-
"""
Generator PPT karya inovasi "SIMBA - Sistem Monitoring Baca Meter".

Jalankan:  python presentasi/buat_ppt.py
Hasil:     presentasi/SIMBA_Presentasi_15menit.pptx   (14 slide, untuk tampil)
           presentasi/SIMBA_Karya_Inovasi.pptx        (lengkap, cadangan tanya jawab)

Kedua berkas dibangun dari SATU naskah di daftar SLIDES di bawah. Tiap butir
boleh diberi:
    hanya="ringkas"   -> hanya masuk berkas 15 menit
    hanya="lengkap"   -> hanya masuk berkas lengkap
    (tanpa "hanya")   -> masuk keduanya

Ubah kalimatnya di SLIDES lalu jalankan ulang - tidak perlu menyentuh kode
layout. Tanda [__] adalah isian yang belum bisa diukur dari kode.

Gambar pendukung diambil dari presentasi/gambar/, dibuat oleh
presentasi/siapkan_gambar.py. Kalau berkas gambarnya belum ada, slide tetap
jadi dengan kotak penampung - jadi urutan menjalankannya bebas.

Angka yang tercantum berasal dari perhitungan ulang atas DPM 202608
(19.915 baris) dengan rule set yang berlaku sekarang.
"""

import os

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# ---------------------------------------------------------------- palet & huruf

NAVY  = RGBColor(0x12, 0x35, 0x5B)
BLUE  = RGBColor(0x1B, 0x98, 0xE0)
GOLD  = RGBColor(0xF2, 0xB7, 0x05)
DGOLD = RGBColor(0xA8, 0x7F, 0x04)
RED   = RGBColor(0xC0, 0x39, 0x2B)
GREEN = RGBColor(0x1E, 0x7A, 0x4B)
GREY  = RGBColor(0x5A, 0x6B, 0x7B)
LIGHT = RGBColor(0xF2, 0xF6, 0xFA)
LINE  = RGBColor(0xD7, 0xE1, 0xEA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PALE  = RGBColor(0xC9, 0xD8, 0xE6)
HIJAU_MUDA = RGBColor(0xE8, 0xF4, 0xEC)
MERAH_MUDA = RGBColor(0xFD, 0xF0, 0xEE)

FONT = "Segoe UI"

W, H = Inches(13.333), Inches(7.5)
ML, MR = Inches(0.75), Inches(0.75)
CW = W - ML - MR                      # lebar area isi
TOP = Inches(1.62)                    # batas atas area isi
BOT = Inches(6.85)                    # batas bawah area isi

DECK = "SIMBA - Sistem Monitoring Baca Meter"
DIR = os.path.dirname(os.path.abspath(__file__))
GAMBAR_DIR = os.path.join(DIR, "gambar")
OUT_RINGKAS = os.path.join(DIR, "SIMBA_Presentasi_15menit.pptx")
OUT_LENGKAP = os.path.join(DIR, "SIMBA_Karya_Inovasi.pptx")

# ================================================================== N A S K A H

SLIDES = [

 # 1 ---------------------------------------------------------------- cover
 dict(kind="cover",
      judul="SIMBA",
      anak="Sistem Monitoring Baca Meter",
      subjudul="Verifikasi tagihan listrik yang menyatukan data, riwayat "
               "konsumsi, dan foto meter dalam satu lembar kerja siap koreksi",
      pembeda="Catatan: karya ini adalah alat analisa mandiri yang MENGAMBIL "
              "data foto dari aplikasi SIMBA PLN - bukan bagian dari aplikasi "
              "tersebut.",
      penyaji=[("Disusun oleh", "[__ Nama __]"),
               ("Jabatan", "[__ Jabatan __]"),
               ("Unit", "[__ Unit __]"),
               ("Periode", "[__ Bulan / Tahun __]")],
      notes="Perkenalkan diri singkat. Sebutkan sejak awal bahwa nama SIMBA di "
            "sini adalah nama karya, dan aplikasi SIMBA PLN adalah salah satu "
            "sumber datanya - supaya tidak ada kebingungan sepanjang paparan."),

 # 2 ---------------------------------------------------------------- ringkasan
 dict(kind="kartu",
      judul="Satu kali jalan: dari file mentah sampai berkas koreksi",
      kicker="RINGKASAN",
      kartu=[("19.915", "pelanggan dianalisis", "satu file DPM, satu bulan"),
             ("2.247",  "perlu diperiksa",      "11,3 % - sisanya lolos bersih"),
             ("2.236",  "baris siap dikoreksi", "827 sudah bersaran otomatis"),
             ("19",     "stand cabut/pasang salah",
              "dari 57 penggantian meter - 1,06 juta kWh menyimpang")],
      catatan="Perhitungan atas DPM periode Agustus 2026 dengan aturan yang "
              "berlaku saat ini. Foto meter tiga bulan terakhir ikut tersemat "
              "di setiap baris yang perlu diperiksa.",
      notes="Slide peta. Katakan: 'ini seluruh isi paparan dalam satu halaman.' "
            "Jangan bahas detail di sini - cukup tunjukkan bahwa hasil akhirnya "
            "bukan laporan, tapi berkas koreksi yang siap diunggah."),

 # 3r --------------------------------------------- latar belakang (versi ringkas)
 dict(kind="dua_kolom", hanya="ringkas",
      judul="Kondisi hari ini, dan apa yang tidak terlihat darinya",
      kicker="LATAR BELAKANG - KONDISI & KETERBATASAN",
      aksen=True,
      kolom=[("YANG DIKERJAKAN SEKARANG", "abu", [
                  "Siklus bulanan yang sama, tanpa template baku",
                  "Sekitar 20.000 pelanggan dalam satu file DPM",
                  "Penyaringan bertumpu pada kode kelainan dari petugas baca",
                  "Angka, riwayat, dan foto dibuka bergantian di tiga tempat"]),
             ("YANG TIDAK BISA DILIHAT DARI SANA", "merah", [
                  "Anomali tanpa kode kelainan tidak pernah muncul",
                  "Pemeriksaan menyeluruh manual tidak terjangkau waktunya",
                  "Kesalahan ganti meter tersembunyi di balik status lain",
                  "Foto tidak sah baru ketahuan setelah dibuka satu per satu"])],
      pita=["Data DPM", "Riwayat konsumsi", "Foto meter SIMBA"],
      pita_teks="Tiga sumber, tiga aplikasi, dibuka bergantian untuk setiap "
                "pelanggan - inilah yang membuat pemeriksaan menyeluruh "
                "mustahil dikerjakan tangan.",
      notes="Kolom kiri adalah alasan awal saya membuat ini. Tapi kolom kanan "
            "yang menentukan: ini bukan soal capek, ini soal ada kesalahan yang "
            "memang tidak mungkin ditemukan dengan cara lama. Tekankan kata "
            "'tidak terlihat'."),

 # 3 ------------------------------------------------- LB 1 (versi lengkap saja)
 dict(kind="butir", hanya="lengkap",
      judul="Bagaimana pemeriksaan rekening dikerjakan hari ini",
      kicker="LATAR BELAKANG 1 dari 3 - KONDISI SAAT INI",
      butir=[("Pekerjaan yang berulang setiap bulan",
              "Siklus yang sama terus diulang tanpa template baku, sehingga "
              "tiap orang punya caranya sendiri."),
             ("Volume yang tidak masuk akal untuk diperiksa satu per satu",
              "Sekitar 20.000 pelanggan per bulan dalam satu file DPM."),
             ("Penyaringan bertumpu pada kode kelainan",
              "Yang tersaring hanyalah apa yang sempat diberi kode oleh "
              "petugas baca meter."),
             ("Bukti tersebar di tiga tempat",
              "Angka di file DPM, riwayat pemakaian di berkas lain, foto meter "
              "di aplikasi SIMBA - dibuka bergantian untuk setiap pelanggan."),
             ("Hasil bergantung pengalaman pemeriksa",
              "Tidak ada urutan prioritas, tidak ada jejak yang bisa "
              "ditelusuri ulang.")],
      notes="Dua butir pertama adalah alasan awal saya membuat ini. Jangan "
            "berhenti di sini - kalau berhenti di sini, pendengar akan berpikir "
            "'template Excel juga cukup'."),

 # 4 ------------------------------------------------- LB 2 (versi lengkap saja)
 dict(kind="butir", hanya="lengkap",
      judul="Masalahnya bukan sekadar lama - ada yang memang tidak terlihat",
      kicker="LATAR BELAKANG 2 dari 3 - KETERBATASAN",
      aksen=True,
      butir=[("Anomali tanpa kode kelainan tidak pernah muncul",
              "Kalau petugas tidak memberi kode, pemakaian seganjil apa pun "
              "lolos tanpa pernah diperiksa."),
             ("Pemeriksaan menyeluruh secara manual tidak terjangkau",
              "20.000 pelanggan dikali membuka tiga sumber - mustahil selesai "
              "dalam satu periode billing."),
             ("Kesalahan penggantian meter tersembunyi di balik status lain",
              "Statusnya tertulis 'Stand Minus' atau 'Stand Tidak Wajar', "
              "sehingga penyebab sebenarnya - stand cabut/pasang - tidak "
              "kelihatan dan salah ditangani."),
             ("Foto yang tidak sah baru ketahuan setelah dibuka",
              "Foto rumah, foto buram, foto salah objek - waktu pemeriksa "
              "terlanjur habis untuk membukanya satu per satu.")],
      notes="Inilah gerakan yang biasanya hilang dari latar belakang."),

 # 5 ---------------------------------------------------------------- NOVELTY
 dict(kind="novelty",
      judul="Kebaruan: bukan pada otomasinya, tapi pada apa yang jadi terlihat",
      kicker="NOVELTY - KEBARUAN",
      aksen=True,
      payung="Menyatukan tiga sumber bukti yang selama ini terpisah - data "
             "tagihan, riwayat konsumsi, dan foto meter - ke dalam satu lembar "
             "kerja yang sudah terklasifikasi, terprioritaskan, dan langsung "
             "dapat ditindaklanjuti sebagai koreksi; ditambah dua kemampuan "
             "yang tidak dimiliki proses eksisting.",
      pilar=[("N1", "Validasi stand cabut/pasang dua segmen",
              "Kelas kesalahan yang selama ini tersembunyi di balik status lain",
              "PROSES"),
             ("N2", "Bukti menyatu dalam satu artefak",
              "Angka, riwayat 6 bulan, dan foto 3 bulan pada baris yang sama",
              "PENYAJIAN"),
             ("N3", "Deteksi dari perilaku konsumsi, bukan kode kelainan",
              "Baseline statistik per pelanggan, tidak menunggu diberi kode",
              "METODE"),
             ("N4", "Computer vision menyaring keabsahan foto",
              "Foto bukan kWh meter dipisahkan sebelum dilihat manusia",
              "TEKNOLOGI"),
             ("N5", "Berhenti di aksi, bukan di laporan",
              "Keluarannya berkas koreksi siap unggah, satu pelanggan satu "
              "koreksi", "PROSES")],
      notes="Slide inti pertama. Bacakan kalimat payungnya pelan-pelan. Lalu "
            "sebutkan bahwa N1 dan N5 adalah kebaruan proses - tidak ada "
            "padanannya; N3 kebaruan metode, N4 kebaruan teknologi, N2 "
            "kebaruan penyajian. Juri menilai originalitas, bukan kecanggihan."),

 # 6 ----------------------------------------------- pembanding (lengkap saja)
 dict(kind="tabel", hanya="lengkap",
      judul="Posisinya dibanding cara dan alat yang sudah ada",
      kicker="PEMBANDING",
      lebar=[3.9, 1.75, 1.85, 1.95, 2.05],
      header=["Kemampuan", "Periksa\nmanual", "Template\nExcel",
              "Kode kelainan\nsistem", "SIMBA\n(karya ini)"],
      baris=[["Menjangkau seluruh pelanggan", "x", "-", "v", "v"],
             ["Membandingkan dengan riwayat pelanggan", "-", "-", "x", "v"],
             ["Foto meter menyatu dengan angkanya", "x", "x", "x", "v"],
             ["Menyaring foto yang tidak sah", "x", "x", "x", "v"],
             ["Memeriksa stand cabut/pasang", "x", "x", "x", "v"],
             ["Menghasilkan berkas koreksi siap unggah", "x", "-", "x", "v"]],
      catatan="✓ = mampu      – = sebagian, bergantung orang      "
              "✕ = tidak mampu",
      notes="Jangan merendahkan cara lama - bingkai sebagai 'masing-masing "
            "punya batas'. Biarkan tabelnya yang berbicara."),

 # 5r ------------------------------------------- masalah & tujuan (ringkas)
 dict(kind="masalah_tujuan", hanya="ringkas",
      judul="Rumusan masalah dan tujuan",
      kicker="MASALAH & TUJUAN - dibaca berpasangan, M1 dijawab T1",
      pasangan=[
        ("Penyaringan hanya bertumpu pada kode kelainan dari petugas baca",
         "Deteksi berbasis riwayat konsumsi per pelanggan"),
        ("Bukti tersebar di tiga sumber, volumenya 20.000 per bulan",
         "Angka, riwayat, dan foto menyatu pada satu baris kerja"),
        ("Tidak ada standar dan urutan prioritas; sulit ditelusuri ulang",
         "Aturan berjenjang dengan ambang tersimpan, hasilnya dapat diaudit"),
        ("Kesalahan stand cabut/pasang tersembunyi di balik status lain",
         "Validasi konsistensi dua segmen di lembar tersendiri"),
        ("Keabsahan foto baru diketahui setelah dibuka satu per satu",
         "Penyaringan foto otomatis dengan model klasifikasi citra"),
        ("Hasil pemeriksaan diketik ulang - rawan salah ketik & koreksi ganda",
         "Berkas koreksi siap unggah, satu pelanggan satu koreksi")],
      notes="Jangan dibacakan semua - cukup katakan 'enam masalah, enam "
            "tujuan, dibaca berpasangan', lalu sebutkan dua yang paling "
            "penting: nomor 4 dan nomor 6."),

 # 7 --------------------------------------------------- masalah (lengkap saja)
 dict(kind="daftar", hanya="lengkap",
      judul="Rumusan masalah",
      kicker="MASALAH",
      awalan="M",
      warna="merah",
      item=["Penyaringan hanya bertumpu pada kode kelainan yang diisi petugas "
            "baca; anomali tanpa kode lolos tanpa pernah diperiksa.",
            "Bukti pemeriksaan tersebar di tiga sumber, sementara volumenya "
            "sekitar 20.000 pelanggan per bulan.",
            "Tidak ada standar dan urutan prioritas; hasil berbeda antar "
            "pemeriksa dan sulit ditelusuri ulang.",
            "Kesalahan stand cabut/pasang tersembunyi di balik status lain dan "
            "justru mendapat saran koreksi yang salah.",
            "Keabsahan foto meter baru diketahui setelah dibuka satu per satu.",
            "Hasil pemeriksaan masih diketik ulang menjadi usulan koreksi - "
            "rawan salah ketik dan koreksi ganda."],
      notes="Enam masalah ini dijawab satu per satu di slide berikutnya."),

 # 8 ---------------------------------------------------- tujuan (lengkap saja)
 dict(kind="daftar", hanya="lengkap",
      judul="Tujuan",
      kicker="TUJUAN - nomornya sejajar dengan rumusan masalah",
      awalan="T",
      warna="hijau",
      item=["Membangun deteksi berbasis riwayat konsumsi per pelanggan, tidak "
            "bergantung pada kode kelainan.",
            "Menyatukan angka, riwayat, dan foto pada satu baris kerja sehingga "
            "verifikasi cukup dalam satu layar.",
            "Menstandarkan pemeriksaan lewat aturan berjenjang dengan ambang "
            "tersimpan, sehingga hasilnya dapat diulang dan diaudit.",
            "Menambahkan validasi konsistensi stand dua segmen dan "
            "memisahkannya ke lembar tersendiri.",
            "Menyaring keabsahan foto meter secara otomatis dengan model "
            "klasifikasi citra.",
            "Menghasilkan berkas koreksi siap unggah: satu pelanggan satu "
            "koreksi, alasan terisi otomatis."],
      notes="Tunjukkan kesejajaran nomornya - M1 dijawab T1, dan seterusnya."),

 # 9 ---------------------------------------------------------------- alur
 dict(kind="alur",
      judul="Cara kerjanya: sembilan tahap, satu tombol",
      kicker="ARSITEKTUR",
      langkah=["Baca file\nDPM", "Cek kelengkapan\nriwayat",
               "Gabung riwayat\n6 bulan", "Analisa 7 aturan\n+ cabut/pasang",
               "Masuk SIMBA", "Ambil & unduh\nfoto meter",
               "Klasifikasi foto\n(YOLOv8)", "Susun Excel",
               "Format &\nsematkan foto"],
      gambar="app_progres.png",
      gambar_ket="Indikator langkah, progres, dan log saat proses berjalan",
      catatan=["Pengguna hanya memilih file dan menekan Jalankan.",
               "Foto diunduh hanya untuk yang perlu diperiksa - 2.247 dari "
               "19.915.",
               "Foto dipakai ulang lintas periode, tidak diunduh dua kali.",
               "Tiap tahap berat bisa dimatikan; proses bisa dibatalkan."],
      notes="Cukup katakan: pengguna hanya memilih file dan menekan Jalankan. "
            "Semua di slide ini terjadi otomatis. Sebutkan efisiensi unduh "
            "foto - itu yang membuat prosesnya tidak berjam-jam."),

 # 10 --------------------------------------------------------------- aturan
 dict(kind="tabel",
      judul="Mesin analisa: tujuh aturan berjenjang, satu pelanggan satu status",
      kicker="METODE",
      lebar=[0.7, 2.6, 5.9, 2.3],
      header=["#", "Aturan", "Kondisi", "Hasil (Agustus 2026)"],
      baris=[["1", "Stand Minus",
              "Stand sekarang lebih kecil dari stand lalu", "699"],
             ["2", "Stand Tidak Wajar",
              "Selisih stand tidak sama dengan pemakaian yang ditagih", "574"],
             ["3", "Meter Macet",
              "Pemakaian nol padahal riwayatnya tidak nol", "95"],
             ["4", "Lebih dari 720 Jam Nyala",
              "Pemakaian melewati batas 720 jam nyala", "117"],
             ["5", "Kenaikan",
              "Naik lebih dari 50 % di atas median 6 bulan dan di atas 150 kWh",
              "319"],
             ["6", "Trend Naik",
              "Naik berturut-turut minimal 3 bulan, total lebih dari 30 %",
              "52"],
             ["7", "Penurunan",
              "Turun lebih dari 50 % di bawah median 6 bulan", "380"]],
      catatan="Aturan diuji berurutan dan berhenti pada yang pertama cocok, "
              "jadi tidak ada pelanggan yang terhitung dua kali. Yang belum "
              "punya riwayat ditandai DATA BARU (11); sisanya Normal (17.668).",
      notes="Tekankan 'berhenti pada yang pertama cocok'. Itu yang membuat "
            "jumlahnya bisa dipertanggungjawabkan. Jangan membacakan semua "
            "barisnya - biarkan pendengar yang membaca."),

 # 11 ------------------------------------------------- ambang (lengkap saja)
 dict(kind="gambar_samping", hanya="lengkap",
      judul="Ambangnya terbuka, bisa disetel, dan tersimpan",
      kicker="TRANSPARANSI",
      gambar="app_pengaturan.png",
      gambar_ket="Dialog Pengaturan Rule di dalam aplikasi",
      butir=[("Sepuluh parameter dapat diubah dari dalam aplikasi",
              "Panjang riwayat pembanding, batas jam nyala, ambang kenaikan "
              "dan penurunan, toleransi selisih stand."),
             ("Diberi penjelasan bahasa sehari-hari",
              "Pengguna tidak perlu membaca kode untuk tahu apa yang diubah."),
             ("Tersimpan dan terbawa antar periode",
              "Hasil bulan ini bisa dibandingkan dengan bulan lalu karena "
              "ambangnya tercatat, bukan diingat-ingat."),
             ("Unit lain bisa memakai ambang berbeda",
              "Karakter pelanggan tiap unit tidak sama.")],
      notes="Ini jawaban untuk pertanyaan juri yang hampir pasti muncul: "
            "'angka 720 dan 50 % itu dari mana?' Jawabannya: bisa disetel, "
            "tercatat, dan bisa diaudit."),

 # 12 ------------------------------------------- UNGGULAN 1 - diagram segmen
 dict(kind="diagram_segmen",
      judul="Kesalahan yang selama ini tersembunyi di balik status lain",
      kicker="UNGGULAN 1 - INI YANG PALING BARU",
      aksen=True,
      rumus="pemakaian ditagih  =  (stand cabut − stand awal)  +  "
            "(stand kini − stand pasang)",
      panel=[dict(judul="SEHARUSNYA", anak="kedua segmen maju",
                  warna="hijau",
                  a=("7.204", "7.284", "+80 kWh"),
                  b=("0", "94", "+94 kWh"),
                  hasil="174 kWh", hasil_ket="cocok dengan tagihan"),
             dict(judul="YANG TERJADI", anak="segmen pertama berbalik arah",
                  warna="merah",
                  a=("11.456", "22", "−11.434 kWh"),
                  b=("22", "11.456", "+11.434 kWh"),
                  hasil="100.000 kWh", hasil_ket="billing pakai rollover meter")],
      temuan=["57 penggantian meter, 19 stand tidak konsisten",
              "Selisih menumpuk 1.061.089 kWh - 10 di antaranya tepat "
              "100.000 kWh",
              "Semuanya berstatus 'Stand Minus' atau 'Stand Tidak Wajar' - "
              "penyebabnya tidak kelihatan"],
      notes="Slide terpenting - beri waktu paling lama. Tunjuk panel bawah: "
            "meter ini sama sekali tidak bergerak, stand awal dan stand kini "
            "sama-sama 11.456. Kedua segmennya saling meniadakan jadi nol kWh. "
            "Tapi karena segmen pertama minus, billing memberlakukan rollover "
            "dan menerbitkan tagihan 100.000 kWh. Itu satu pelanggan, satu "
            "bulan. Poin puncaknya: kesalahan ini tidak lolos karena tidak "
            "diperiksa, tapi karena statusnya menunjuk ke arah yang salah."),

 # 13 --------------------------------------------- bukti lembar CABUT_PASANG
 dict(kind="gambar",
      judul="Lembarnya sendiri yang mengangkat penyebabnya ke permukaan",
      kicker="BUKTI - LEMBAR CABUT_PASANG",
      aksen=True,
      gambar="excel_cabut_pasang.png",
      gambar_ket="Lembar CABUT_PASANG - stand yang jadi penyebab masalah "
                 "disorot merah otomatis",
      catatan=["Hanya baris bermasalah yang masuk, diurutkan dari selisih "
               "terbesar.",
               "Kolom penyebabnya disorot langsung, jadi pemeriksa tahu stand "
               "mana yang salah tanpa menghitung ulang.",
               "Baris ini dikunci agar hanya dikoreksi dari sini - supaya satu "
               "pelanggan tidak dapat dua usulan koreksi."],
      notes="Katakan: inilah wujud nyatanya. Kalau sempat, buka file aslinya "
            "sebentar - satu tampilan asli lebih meyakinkan daripada lima "
            "slide penjelasan."),

 # 14 ------------------------------------------- unggulan 2 (lengkap saja)
 dict(kind="butir", hanya="lengkap",
      judul="Fotonya datang sendiri, dan sudah disaring lebih dulu",
      kicker="UNGGULAN 2",
      aksen=True,
      butir=[("Foto diambil otomatis dari SIMBA, tiga bulan sekaligus",
              "Pemeriksa bisa membandingkan foto bulan ini dengan dua bulan "
              "sebelumnya tanpa membuka aplikasi lain."),
             ("Diunduh paralel, dan hanya untuk yang perlu",
              "Dua kelompok pekerja berjalan bersamaan; unduhan dimulai begitu "
              "alamat foto pertama didapat."),
             ("Sekali diunduh, dipakai seterusnya",
              "Foto disimpan menurut bulannya sendiri sehingga periode "
              "berikutnya tidak mengunduh ulang."),
             ("Model YOLOv8 memisahkan foto kWh meter dari yang bukan",
              "Dikumpulkan di lembar BUKAN_KWH - petunjuk kuat bahwa stand-nya "
              "tidak dapat dipercaya."),
             ("Kalau model tidak tersedia, proses tetap jalan",
              "Tahap ini dilewati, bukan menggagalkan seluruh analisa.")],
      notes="Foto bukan kWh meter bukan sekadar gangguan - itu sinyal."),

 # 15 ------------------------------------------------ UNGGULAN 2 - galeri foto
 dict(kind="galeri_foto",
      judul="Foto meternya disaring mesin sebelum dilihat manusia",
      kicker="UNGGULAN 2 - COMPUTER VISION",
      aksen=True,
      foto=[("foto_kwh_meter.png", "kwh_meter", "hijau",
             "Foto sah - stand bisa diverifikasi dari gambar"),
            ("foto_bukan_kwh.png", "bukan_kwh", "merah",
             "Bukan meter - stand yang dilaporkan patut dipertanyakan")],
      catatan=["Model YOLOv8 melabeli foto terbaru setiap pelanggan, lalu yang "
               "bukan meter dikumpulkan di lembar BUKAN_KWH.",
               "Label ini juga dipakai memperbaiki saran koreksi: stand minus "
               "yang fotonya bukan meter disarankan diganti rata-rata, bukan "
               "dianggap rumah kosong.",
               "Kalau model tidak terpasang, tahap ini dilewati dan analisa "
               "tetap berjalan."],
      notes="Tunjuk foto kanan: ini yang selama ini baru ketahuan setelah "
            "pemeriksa membukanya satu per satu. Sekarang sudah terkumpul "
            "sendiri di satu lembar sebelum dibuka."),

 # 16 --------------------------------------- unggulan 3 kartu (lengkap saja)
 dict(kind="kartu_teks", hanya="lengkap",
      judul="Berhenti di laporan itu baru setengah pekerjaan",
      kicker="UNGGULAN 3",
      aksen=True,
      kartu=[("2.236", "baris masuk lembar koreksi"),
             ("827",   "sudah bersaran otomatis"),
             ("9",     "pilihan alasan koreksi"),
             ("1",     "koreksi per pelanggan - tidak boleh ganda")],
      butir=[("Pemeriksa cukup memilih dari daftar",
              "Begitu pilihan diubah, kolom STAN BARU dan ALASAN KOREKSI "
              "terisi sendiri lewat rumus - tidak ada yang diketik ulang."),
             ("Saran awal sudah terisi untuk kasus yang jelas",
              "679 rumah kosong, 128 pembatasan 720 jam nyala, 20 diganti "
              "rata-rata karena fotonya tidak terbaca."),
             ("Satu pelanggan tidak mungkin punya dua usulan koreksi",
              "Baris bermasalah cabut/pasang dikunci agar hanya dikoreksi dari "
              "lembar CABUT_PASANG.")],
      notes="Keluarannya bukan bahan bacaan, tapi bahan unggah."),

 # 17 ------------------------------------- UNGGULAN 3 - lembar KOREKSI_STAND
 dict(kind="gambar_samping",
      judul="Berhenti di laporan itu baru setengah pekerjaan",
      kicker="UNGGULAN 3 - KOREKSI SIAP UNGGAH",
      aksen=True,
      gambar="excel_koreksi_stand.png",
      gambar_ket="Lembar KOREKSI_STAND - kolom STAN BARU dan ALASAN KOREKSI "
                 "terisi sendiri lewat rumus",
      butir=[("2.236 baris siap dikoreksi, 827 sudah bersaran otomatis",
              "679 rumah kosong, 128 pembatasan 720 jam nyala, 20 diganti "
              "rata-rata karena fotonya tidak terbaca."),
             ("Pemeriksa cukup memilih dari daftar sembilan pilihan",
              "Stand baru dan alasannya terisi sendiri - tidak ada yang "
              "perlu diketik ulang."),
             ("Satu pelanggan tidak mungkin punya dua usulan koreksi",
              "Kalau sampai ganda, unggahannya akan bentrok di sistem.")],
      notes="Inilah yang membedakan dari alat analitik pada umumnya. Sebutkan "
            "aturan satu pelanggan satu koreksi - detail itu menunjukkan alat "
            "ini dipikirkan sampai ke ujung prosesnya."),

 # 18 ------------------------------------------- anatomi excel (lengkap saja)
 dict(kind="gambar_samping", hanya="lengkap",
      judul="Hasilnya satu berkas Excel yang sudah tertata",
      kicker="KELUARAN",
      gambar="excel_baris_foto.png",
      gambar_ket="Satu baris kerja: angka, riwayat, dan foto meter menyatu",
      butir=[("Satu lembar untuk setiap jenis temuan",
              "Stand Minus, Stand Tidak Wajar, Kenaikan, Penurunan, Meter "
              "Macet, di atas 720 Jam Nyala, Trend Naik."),
             ("Lembar khusus untuk yang butuh perhatian tersendiri",
              "CABUT_PASANG, BUKAN_KWH, dan KOREKSI_STAND."),
             ("Kolom diberi kode warna menurut asal datanya",
              "Biru dari rekening, hijau dari stan baca, ungu rata-rata, "
              "tosca cabut/pasang, emas kolom isian pemeriksa."),
             ("Riwayat terbaca sekilas",
              "Grafik batang mini menunjukkan pola enam bulan terakhir.")],
      notes="Kalau memungkinkan, buka file hasilnya sebentar di sini."),

 # 19 ------------------------------------------------------ sebelum vs sesudah
 dict(kind="tabel",
      judul="Yang berubah bagi pemeriksa",
      kicker="DAMPAK",
      lebar=[3.3, 4.3, 4.3],
      header=["", "Sebelum", "Sesudah"],
      baris=[["Cakupan", "Sebagian, sesuai waktu yang tersisa",
              "Seluruh 19.915 pelanggan tersaring"],
             ["Yang tersaring", "Hanya yang diberi kode kelainan",
              "Juga yang menyimpang dari riwayatnya sendiri"],
             ["Bukti", "Dibuka di tiga aplikasi berbeda",
              "Menyatu pada satu baris, foto ikut tersemat"],
             ["Urutan kerja", "Menurut selera pemeriksa",
              "Terkelompok dan terurut menurut kegentingan"],
             ["Cabut / pasang", "Tidak diperiksa; sarannya justru salah",
              "19 temuan terangkat lengkap dengan penyebabnya"],
             ["Keluaran", "Catatan yang diketik ulang",
              "Berkas koreksi siap unggah"]],
      catatan="Manfaat waktu: [__] jam-orang per bulan sebelumnya, menjadi "
              "[__] jam-orang. Manfaat mutu: cakupan penuh, hasil dapat "
              "diulang, dan ada jejak yang bisa ditelusuri saat diaudit.",
      notes="Baris 'Cabut / pasang' yang paling kuat - satu-satunya baris yang "
            "bukan soal kecepatan, tapi soal temuan yang sebelumnya tidak ada "
            "sama sekali. Isi dulu angka [__] sebelum presentasi."),

 # 20 ---------------------------------------------- manfaat (lengkap saja)
 dict(kind="manfaat", hanya="lengkap",
      judul="Manfaat yang bisa dipertanggungjawabkan",
      kicker="MANFAAT",
      kolom=[("WAKTU",
              ["Pemeriksaan manual: [__] jam-orang per bulan",
               "Dengan aplikasi: [__] jam-orang per bulan",
               "Penghematan: [__] jam-orang per bulan",
               "Foto tidak diunduh ulang antar periode"]),
             ("MUTU",
              ["Cakupan naik dari sebagian menjadi seluruh pelanggan",
               "Hasil dapat diulang - ambang tercatat, bukan diingat",
               "Ada jejak yang bisa ditelusuri saat diaudit",
               "Saran koreksi seragam antar pemeriksa"]),
             ("RISIKO YANG DICEGAH",
              ["Tagihan mustahil akibat rollover meter",
               "Koreksi rekening susulan dan keluhan pelanggan",
               "Koreksi ganda pada pelanggan yang sama",
               "Stand yang dipercaya padahal fotonya bukan meter"])],
      catatan="Isi bagian [__] dengan hasil pengukuran sendiri. Pengukuran "
              "kasar yang jujur lebih kuat daripada angka besar yang tidak "
              "bisa dijelaskan asalnya.",
      notes="Sengaja tidak mencantumkan nilai rupiah. Kalau ditanya, jawab: "
            "belum diukur, dan lebih baik tidak mengklaim daripada mengklaim "
            "yang tidak bisa dibuktikan."),

 # 21 -------------------------------------------- replikasi (lengkap saja)
 dict(kind="gambar_samping", hanya="lengkap",
      judul="Sudah bisa dipakai, dan mudah dipindahkan ke unit lain",
      kicker="IMPLEMENTASI",
      gambar="app_utama.png",
      gambar_ket="Jendela utama aplikasi",
      butir=[("Berbentuk installer Windows biasa",
              "Dipasang seperti aplikasi lain, tidak perlu memasang Python "
              "atau peralatan pengembang."),
             ("Tidak butuh server dan tidak menambah basis data baru",
              "Berjalan di komputer pengguna, memakai data yang sudah ada."),
             ("Pindah unit hanya perlu mengganti dua hal",
              "Berkas riwayat unit tersebut dan akun SIMBA-nya; kode unit "
              "terbaca sendiri dari nama pengguna."),
             ("Ambang bisa disesuaikan per unit",
              "Karakter pelanggan tiap unit berbeda."),
             ("Setiap bagian berat bisa dimatikan",
              "Bila jaringan SIMBA atau model tidak tersedia, analisa tetap "
              "berjalan tanpa bagian tersebut.")],
      notes="Replikabilitas adalah salah satu kriteria penilaian."),

 # 22 --------------------------------------------- roadmap (lengkap saja)
 dict(kind="roadmap", hanya="lengkap",
      judul="Yang sedang dan akan dikerjakan",
      kicker="PENGEMBANGAN LANJUT",
      tahap=[("SUDAH BERJALAN",
              ["Deteksi anomali dari riwayat konsumsi",
               "Foto meter tersemat otomatis",
               "Penyaringan foto dengan computer vision",
               "Validasi stand cabut/pasang",
               "Berkas koreksi siap unggah"]),
             ("SEDANG DISEMPURNAKAN",
              ["Pembacaan angka meter langsung dari foto - model dua tahap "
               "sudah terbangun, sedang dikalibrasi ketelitiannya sebelum "
               "diaktifkan",
               "Pembandingan silang stan baca petugas dengan stand yang "
               "ditagihkan"]),
             ("RENCANA BERIKUTNYA",
              ["Pemberian skor kegentingan, bukan sekadar pengelompokan",
               "Pengiriman hasil koreksi langsung ke sistem",
               "Uji coba di unit lain"])],
      notes="Penting untuk kejujuran: pembacaan angka meter dari foto BELUM "
            "aktif. Kalau ditanya, katakan apa adanya."),

 # 13r ------------------------------- siap pakai + pengembangan (ringkas)
 dict(kind="dua_kolom", hanya="ringkas",
      judul="Sudah bisa dipakai, dan masih akan berkembang",
      kicker="IMPLEMENTASI & PENGEMBANGAN LANJUT",
      kolom=[("SUDAH SIAP PAKAI", "hijau", [
                  "Berbentuk installer Windows biasa",
                  "Tidak butuh server, tidak menambah basis data baru",
                  "Pindah unit cukup ganti berkas riwayat dan akun SIMBA",
                  "Ambang bisa disetel sendiri per unit",
                  "Tiap bagian berat bisa dimatikan, analisa tetap jalan"]),
             ("SEDANG DIKERJAKAN", "biru", [
                  "Pembacaan angka meter dari foto - model sudah ada, "
                  "ketelitiannya sedang dikalibrasi",
                  "Pembandingan silang stan baca petugas vs stand ditagihkan",
                  "Pemberian skor kegentingan, bukan sekadar pengelompokan",
                  "Uji coba di unit lain"])],
      notes="Kolom kanan penting untuk kejujuran: pembacaan angka meter dari "
            "foto BELUM aktif. Kalau ditanya, katakan apa adanya - modelnya "
            "sudah ada, ketelitiannya belum memadai untuk dipakai memutuskan "
            "tagihan orang. Kehati-hatian itu justru nilai tambah."),

 # 23 --------------------------------------------------------------- penutup
 dict(kind="penutup",
      judul="Terima kasih",
      pesan="Yang baru dari karya ini bukan kecepatannya, melainkan hal-hal "
            "yang akhirnya terlihat: penyimpangan yang tidak pernah diberi "
            "kode, foto yang ternyata bukan meter, dan kesalahan penggantian "
            "meter yang selama ini tersembunyi di balik status lain.",
      ajakan=["Siap diuji coba pada data unit lain",
              "Masukan dari pemeriksa sangat dibutuhkan untuk penyetelan ambang",
              "Kontak: [__ nama / unit / kontak __]"],
      notes="Tutup dengan mengulang kalimat kebaruan sekali lagi. Lalu diam "
            "sejenak dan buka sesi tanya jawab."),
]

# ============================================================ K O D E  L A Y O U T

prs = None
BLANK = None

WARNA = {"hijau": GREEN, "merah": RED, "biru": BLUE, "emas": DGOLD,
         "abu": GREY, "navy": NAVY}


def _style(shape, size, color, bold, align):
    tf = shape.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.font.size, r.font.bold, r.font.name = Pt(size), bold, FONT
    r.font.color.rgb = color
    return tf, p, r


def text(slide, x, y, w, h, s, size=14, color=NAVY, bold=False,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=None,
         italic=False):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf, p, r = _style(box, size, color, bold, align)
    r.text = s
    r.font.italic = italic
    tf.vertical_anchor = anchor
    if spacing:
        p.line_spacing = spacing
    return box


def rect(slide, x, y, w, h, fill=None, line=None, radius=None):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        x, y, w, h)
    if radius:
        try:
            shp.adjustments[0] = radius
        except Exception:
            pass
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    shp.shadow.inherit = False
    return shp


def dot(slide, x, y, color=GOLD, size=Inches(0.1)):
    rect(slide, x, y, size, size, fill=color)


def gambar(s, nama, x, y, w, h, ket=None):
    """Sisipkan PNG dengan menjaga rasio; kalau berkasnya belum ada, gambar
    kotak penampung supaya slide tetap jadi dan jelas apa yang kurang.

    Mengembalikan (x, y, lebar, tinggi) gambar yang benar-benar terpasang -
    dipakai pemanggil yang perlu meratakan label tepat selebar gambarnya.
    """
    ket_h = Inches(0.32) if ket else Emu(0)
    kotak_h = h - ket_h
    p = os.path.join(GAMBAR_DIR, nama)
    if os.path.exists(p):
        try:
            from PIL import Image
            iw, ih = Image.open(p).size
            skala = min(kotak_h / ih, w / iw)
            nw, nh = int(iw * skala), int(ih * skala)
        except Exception:
            nw, nh = w, kotak_h
        gx, gy = x + (w - nw) // 2, y + (kotak_h - nh) // 2
        s.shapes.add_picture(p, gx, gy, nw, nh)
        rect(s, gx, gy, nw, nh, fill=None, line=LINE)
    else:
        gx, gy, nw, nh = x, y, w, kotak_h
        rect(s, x, y, w, kotak_h, fill=LIGHT, line=LINE)
        text(s, x, y, w, kotak_h,
             "[ gambar belum dibuat ]\n" + nama + "\n\n"
             "jalankan: python presentasi/siapkan_gambar.py",
             size=11, color=GREY, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE, spacing=1.3)
    if ket:
        text(s, x, y + kotak_h + Inches(0.06), w, Inches(0.28), ket,
             size=10.5, color=GREY, align=PP_ALIGN.CENTER, italic=True)
    return gx, gy, nw, nh


def base(d, nomor):
    """Kerangka slide: bilah aksen, kicker, judul, garis, footer, nomor."""
    s = prs.slides.add_slide(BLANK)
    if d.get("aksen"):
        rect(s, Emu(0), Emu(0), Inches(0.13), H, fill=GOLD)
    if d.get("kicker"):
        text(s, ML, Inches(0.42), CW, Inches(0.3), d["kicker"].upper(),
             size=11, color=BLUE, bold=True)
    text(s, ML, Inches(0.74), CW, Inches(0.8), d["judul"], size=26,
         color=NAVY, bold=True, spacing=0.95)
    rect(s, ML, Inches(1.42), Inches(1.4), Pt(3), fill=GOLD)
    text(s, ML, Inches(7.02), Inches(9), Inches(0.3), DECK, size=9, color=GREY)
    text(s, W - MR - Inches(1), Inches(7.02), Inches(1), Inches(0.3),
         str(nomor), size=9, color=GREY, align=PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = d.get("notes", "")
    return s


def bullet_list(s, items, top, bottom, kiri=None, lebar=None,
                size=14, sub_size=12):
    kiri = ML if kiri is None else kiri
    lebar = (CW if lebar is None else lebar)
    n = len(items)
    gap = Inches(0.14)
    ih = int((bottom - top - gap * (n - 1)) / n)
    y = top
    for judul, detail in items:
        dot(s, kiri, y + Inches(0.13))
        text(s, kiri + Inches(0.28), y, lebar - Inches(0.28), Inches(0.34),
             judul, size=size, color=NAVY, bold=True, spacing=1.0)
        if detail:
            text(s, kiri + Inches(0.28), y + Inches(0.32),
                 lebar - Inches(0.28), ih - Inches(0.32), detail,
                 size=sub_size, color=GREY, spacing=1.08)
        y += ih + gap


# ------------------------------------------------------------------ pembangun

def build_cover(d, nomor):
    s = prs.slides.add_slide(BLANK)
    rect(s, Emu(0), Emu(0), W, Inches(3.55), fill=NAVY)
    rect(s, Emu(0), Inches(3.55), W, Pt(5), fill=GOLD)
    text(s, ML, Inches(0.62), CW, Inches(0.35), "KARYA INOVASI",
         size=13, color=GOLD, bold=True)
    text(s, ML, Inches(1.0), CW, Inches(1.1), d["judul"], size=56,
         color=WHITE, bold=True)
    text(s, ML, Inches(2.0), CW, Inches(0.45), d["anak"], size=22,
         color=BLUE, bold=True)
    text(s, ML, Inches(2.5), Inches(10.2), Inches(0.9), d["subjudul"],
         size=14, color=PALE, spacing=1.2)
    box = rect(s, ML, Inches(3.95), CW, Inches(0.78), fill=LIGHT,
               line=LINE, radius=0.05)
    tf, p, r = _style(box, 11.5, GREY, False, PP_ALIGN.LEFT)
    r.text = d["pembeda"]
    tf.margin_left = tf.margin_right = Inches(0.2)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p.line_spacing = 1.15
    # Dua kolom supaya titik duanya sejajar - spasi tidak bisa dipakai
    # meratakan pada huruf berlebar tidak tetap seperti Segoe UI.
    y = Inches(5.1)
    for label, isi in d["penyaji"]:
        text(s, ML, y, Inches(1.7), Inches(0.34), label + " :", size=14,
             color=GREY)
        text(s, ML + Inches(1.8), y, Inches(6), Inches(0.34), isi, size=14,
             color=NAVY, bold=True)
        y += Inches(0.4)
    text(s, ML, Inches(7.02), Inches(9), Inches(0.3),
         "Isi bagian [__] sebelum dipresentasikan.", size=9, color=GREY)
    s.notes_slide.notes_text_frame.text = d.get("notes", "")


def build_kartu(d, nomor):
    s = base(d, nomor)
    n = len(d["kartu"])
    gap = Inches(0.26)
    cwid = int((CW - gap * (n - 1)) / n)
    tinggi = Inches(3.5)          # kartu dibesarkan supaya mengisi halaman
    x = ML
    for angka, label, ket in d["kartu"]:
        rect(s, x, TOP, cwid, tinggi, fill=LIGHT, line=LINE, radius=0.04)
        rect(s, x, TOP, cwid, Pt(5), fill=BLUE)
        text(s, x + Inches(0.24), TOP + Inches(0.5), cwid - Inches(0.48),
             Inches(1.0), angka, size=48, color=NAVY, bold=True)
        text(s, x + Inches(0.24), TOP + Inches(1.6), cwid - Inches(0.48),
             Inches(0.7), label, size=14, color=NAVY, bold=True, spacing=1.05)
        text(s, x + Inches(0.24), TOP + Inches(2.45), cwid - Inches(0.48),
             Inches(0.8), ket, size=11.5, color=GREY, spacing=1.12)
        x += cwid + gap
    text(s, ML, TOP + tinggi + Inches(0.35), CW, Inches(0.9), d["catatan"],
         size=13, color=GREY, spacing=1.2)


def build_kartu_teks(d, nomor):
    s = base(d, nomor)
    n = len(d["kartu"])
    gap = Inches(0.22)
    cwid = int((CW - gap * (n - 1)) / n)
    x = ML
    for angka, label in d["kartu"]:
        rect(s, x, TOP, cwid, Inches(1.34), fill=NAVY, radius=0.06)
        text(s, x + Inches(0.18), TOP + Inches(0.14), cwid - Inches(0.36),
             Inches(0.55), angka, size=29, color=GOLD, bold=True)
        text(s, x + Inches(0.18), TOP + Inches(0.74), cwid - Inches(0.36),
             Inches(0.52), label, size=11, color=WHITE, spacing=1.08)
        x += cwid + gap
    bullet_list(s, d["butir"], TOP + Inches(1.7), BOT)


def build_butir(d, nomor):
    s = base(d, nomor)
    bullet_list(s, d["butir"], TOP, BOT)


def build_daftar(d, nomor):
    s = base(d, nomor)
    warna = RED if d.get("warna") == "merah" else GREEN
    n = len(d["item"])
    gap = Inches(0.13)
    ih = int((BOT - TOP - gap * (n - 1)) / n)
    y = TOP
    for i, isi in enumerate(d["item"], 1):
        rect(s, ML, y, Inches(0.62), ih, fill=warna, radius=0.14)
        text(s, ML, y, Inches(0.62), ih, "%s%d" % (d["awalan"], i),
             size=16, color=WHITE, bold=True, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE)
        text(s, ML + Inches(0.84), y, CW - Inches(0.84), ih, isi,
             size=14, color=NAVY, anchor=MSO_ANCHOR.MIDDLE, spacing=1.14)
        y += ih + gap


def build_masalah_tujuan(d, nomor):
    """Masalah dan tujuan bersebelahan supaya kesejajarannya langsung terlihat."""
    s = base(d, nomor)
    n = len(d["pasangan"])
    gap = Inches(0.12)
    ih = int((BOT - TOP - Inches(0.5) - gap * (n - 1)) / n)
    kol = int((CW - Inches(0.9)) / 2)
    kiri_x = ML + Inches(0.5)
    kanan_x = ML + Inches(0.5) + kol + Inches(0.4)

    text(s, kiri_x, TOP, kol, Inches(0.32), "MASALAH", size=12,
         color=RED, bold=True)
    text(s, kanan_x, TOP, kol, Inches(0.32), "TUJUAN", size=12,
         color=GREEN, bold=True)

    y = TOP + Inches(0.5)
    for i, (m, t) in enumerate(d["pasangan"], 1):
        rect(s, ML, y, Inches(0.42), ih, fill=NAVY, radius=0.2)
        text(s, ML, y, Inches(0.42), ih, str(i), size=13, color=GOLD,
             bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        rect(s, kiri_x, y, kol, ih, fill=MERAH_MUDA, radius=0.05)
        text(s, kiri_x + Inches(0.16), y, kol - Inches(0.32), ih, m,
             size=12, color=NAVY, anchor=MSO_ANCHOR.MIDDLE, spacing=1.12)
        text(s, kiri_x + kol + Inches(0.06), y, Inches(0.28), ih, "→",
             size=14, color=GOLD, bold=True, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE)
        rect(s, kanan_x, y, kol, ih, fill=HIJAU_MUDA, radius=0.05)
        text(s, kanan_x + Inches(0.16), y, kol - Inches(0.32), ih, t,
             size=12, color=NAVY, anchor=MSO_ANCHOR.MIDDLE, spacing=1.12)
        y += ih + gap


def build_dua_kolom(d, nomor):
    s = base(d, nomor)
    punya_pita = bool(d.get("pita"))
    bawah = BOT - (Inches(1.5) if punya_pita else Emu(0))
    gap = Inches(0.4)
    kol = int((CW - gap) / 2)
    x = ML
    for judul, warna_nama, butir in d["kolom"]:
        c = WARNA.get(warna_nama, GREY)
        rect(s, x, TOP, kol, bawah - TOP, fill=LIGHT, line=LINE, radius=0.03)
        rect(s, x, TOP, kol, Pt(6), fill=c)
        text(s, x + Inches(0.24), TOP + Inches(0.26), kol - Inches(0.48),
             Inches(0.32), judul, size=12, color=c, bold=True)
        atas = TOP + Inches(0.85)
        slot = min(Inches(1.05), int((bawah - atas - Inches(0.2)) / len(butir)))
        yy = atas
        for b in butir:
            dot(s, x + Inches(0.26), yy + Inches(0.09), c, Inches(0.09))
            text(s, x + Inches(0.48), yy, kol - Inches(0.74), slot, b,
                 size=12.5, color=NAVY, spacing=1.18)
            yy += slot
        x += kol + gap

    if punya_pita:
        py = bawah + Inches(0.28)
        n = len(d["pita"])
        cw = Inches(2.3)
        total = cw * n + Inches(0.42) * (n - 1)
        px = ML + (CW - total) // 2
        for i, nama in enumerate(d["pita"]):
            rect(s, px, py, cw, Inches(0.46), fill=WHITE, line=GREY,
                 radius=0.14)
            text(s, px, py, cw, Inches(0.46), nama, size=11.5, color=NAVY,
                 bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
            if i < n - 1:
                text(s, px + cw, py, Inches(0.42), Inches(0.46), "✕",
                     size=15, color=RED, bold=True, align=PP_ALIGN.CENTER,
                     anchor=MSO_ANCHOR.MIDDLE)
            px += cw + Inches(0.42)
        text(s, ML, py + Inches(0.6), CW, Inches(0.5), d["pita_teks"],
             size=12, color=GREY, align=PP_ALIGN.CENTER, spacing=1.15)


def build_tabel(d, nomor):
    s = base(d, nomor)
    ncol, nrow = len(d["header"]), len(d["baris"]) + 1
    ada_catatan = bool(d.get("catatan"))
    tinggi = BOT - TOP - (Inches(0.86) if ada_catatan else Emu(0))
    tbl = s.shapes.add_table(nrow, ncol, ML, TOP, CW, tinggi).table
    tbl.first_row = True
    for i, wl in enumerate(d["lebar"]):
        tbl.columns[i].width = Inches(wl)
    kepala = Inches(0.66)
    tbl.rows[0].height = kepala
    for r in range(1, nrow):
        tbl.rows[r].height = int((tinggi - kepala) / (nrow - 1))

    for c, h in enumerate(d["header"]):
        cell = tbl.cell(0, c)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = NAVY
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = cell.margin_right = Inches(0.1)
        for p in cell.text_frame.paragraphs:
            p.alignment = PP_ALIGN.CENTER if c else PP_ALIGN.LEFT
            for r in p.runs:
                r.font.size, r.font.bold, r.font.name = Pt(12), True, FONT
                r.font.color.rgb = WHITE

    tanda = {"v": ("✓", GREEN), "x": ("✕", RED), "-": ("–", DGOLD)}
    for ri, baris in enumerate(d["baris"], 1):
        for ci, val in enumerate(baris):
            cell = tbl.cell(ri, ci)
            sim = tanda.get(val)
            cell.text = sim[0] if sim else val
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE if ri % 2 else LIGHT
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = cell.margin_right = Inches(0.1)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            for p in cell.text_frame.paragraphs:
                p.alignment = PP_ALIGN.CENTER if sim else PP_ALIGN.LEFT
                for r in p.runs:
                    r.font.name = FONT
                    if sim:
                        r.font.size, r.font.bold = Pt(16), True
                        r.font.color.rgb = sim[1]
                    else:
                        r.font.size = Pt(11.5)
                        r.font.bold = (ci == 0)
                        r.font.color.rgb = NAVY if ci == 0 else GREY

    if ada_catatan:
        text(s, ML, BOT - Inches(0.74), CW, Inches(0.74), d["catatan"],
             size=11.5, color=GREY, spacing=1.15)


def build_alur(d, nomor):
    s = base(d, nomor)
    baris = [d["langkah"][:5], d["langkah"][5:]]
    gap = Inches(0.3)
    # Lebar kotak dikunci pada baris terpanjang supaya kedua baris sejajar -
    # kalau dihitung per baris, baris kedua jadi lebih lebar dan terlihat miring.
    per_baris = max(len(r) for r in baris)
    bw = int((CW - gap * (per_baris - 1)) / per_baris)
    bh = Inches(0.88) if d.get("gambar") else Inches(1.0)
    y = TOP
    for row in baris:
        x = ML
        for i, t in enumerate(row):
            rect(s, x, y, bw, bh, fill=LIGHT, line=BLUE, radius=0.07)
            text(s, x + Inches(0.08), y, bw - Inches(0.16), bh, t,
                 size=11.5, color=NAVY, bold=True, align=PP_ALIGN.CENTER,
                 anchor=MSO_ANCHOR.MIDDLE, spacing=1.0)
            if i < len(row) - 1:
                text(s, x + bw, y, gap, bh, ">", size=18,
                     color=GOLD, bold=True, align=PP_ALIGN.CENTER,
                     anchor=MSO_ANCHOR.MIDDLE)
            x += bw + gap
        y += bh + Inches(0.26)

    y += Inches(0.24)
    if d.get("gambar"):
        gw = Inches(5.6)
        gambar(s, d["gambar"], W - MR - gw, y, gw, BOT - y,
               d.get("gambar_ket"))
        lebar_teks = CW - gw - Inches(0.45)
    else:
        lebar_teks = CW
    for c in d["catatan"]:
        dot(s, ML, y + Inches(0.1))
        text(s, ML + Inches(0.28), y, lebar_teks - Inches(0.28), Inches(0.56),
             c, size=12.5, color=GREY, spacing=1.12)
        y += Inches(0.58)


def build_diagram_segmen(d, nomor):
    """Linimasa dua segmen: versi sehat di atas, versi rusak di bawah."""
    s = base(d, nomor)
    rect(s, ML, TOP, CW, Inches(0.5), fill=NAVY, radius=0.08)
    text(s, ML, TOP, CW, Inches(0.5), d["rumus"], size=14, color=GOLD,
         bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    ph = Inches(1.55)
    py = TOP + Inches(0.72)
    for pan in d["panel"]:
        c = WARNA[pan["warna"]]
        latar = HIJAU_MUDA if pan["warna"] == "hijau" else MERAH_MUDA
        rect(s, ML, py, CW, ph, fill=latar, line=c, radius=0.03)
        rect(s, ML, py, Pt(5), ph, fill=c)

        text(s, ML + Inches(0.22), py + Inches(0.3), Inches(1.6), Inches(0.3),
             pan["judul"], size=12.5, color=c, bold=True)
        text(s, ML + Inches(0.22), py + Inches(0.62), Inches(1.6),
             Inches(0.5), pan["anak"], size=10.5, color=GREY, spacing=1.1)

        # dua batang segmen + jeda "ganti meter" di tengahnya
        sx = ML + Inches(1.95)
        sw = Inches(2.85)
        jeda = Inches(0.62)
        for i, (mulai, akhir, delta) in enumerate((pan["a"], pan["b"])):
            x = sx + i * (sw + jeda)
            minus = delta.startswith("−")
            bc = RED if minus else GREEN
            text(s, x, py + Inches(0.26), sw, Inches(0.26), mulai,
                 size=11.5, color=NAVY, bold=True)
            text(s, x, py + Inches(0.26), sw, Inches(0.26), akhir,
                 size=11.5, color=NAVY, bold=True, align=PP_ALIGN.RIGHT)
            rect(s, x, py + Inches(0.6), sw, Inches(0.42), fill=bc, radius=0.2)
            text(s, x, py + Inches(0.6), sw, Inches(0.42), delta, size=12,
                 color=WHITE, bold=True, align=PP_ALIGN.CENTER,
                 anchor=MSO_ANCHOR.MIDDLE)
            label = "segmen meter lama" if i == 0 else "segmen meter baru"
            text(s, x, py + Inches(1.06), sw, Inches(0.26), label,
                 size=9.5, color=GREY, align=PP_ALIGN.CENTER)
            if i == 0:
                text(s, x + sw, py + Inches(0.6), jeda, Inches(0.42), "⇄",
                     size=14, color=GREY, bold=True, align=PP_ALIGN.CENTER,
                     anchor=MSO_ANCHOR.MIDDLE)
                text(s, x + sw - Inches(0.3), py + Inches(1.06),
                     jeda + Inches(0.6), Inches(0.26), "ganti meter",
                     size=9, color=GREY, align=PP_ALIGN.CENTER)

        hx = sx + 2 * sw + jeda + Inches(0.3)
        hw = W - MR - Inches(0.2) - hx
        rect(s, hx, py + Inches(0.32), hw, Inches(0.86), fill=WHITE,
             line=c, radius=0.06)
        text(s, hx, py + Inches(0.42), hw, Inches(0.4), pan["hasil"],
             size=17, color=c, bold=True, align=PP_ALIGN.CENTER)
        text(s, hx + Inches(0.1), py + Inches(0.84), hw - Inches(0.2),
             Inches(0.3), pan["hasil_ket"], size=10, color=GREY,
             align=PP_ALIGN.CENTER)
        py += ph + Inches(0.2)

    ty = py + Inches(0.14)
    n = len(d["temuan"])
    gap = Inches(0.24)
    tw = int((CW - gap * (n - 1)) / n)
    x = ML
    for t in d["temuan"]:
        rect(s, x, ty, tw, BOT - ty, fill=LIGHT, line=LINE, radius=0.05)
        dot(s, x + Inches(0.2), ty + Inches(0.24))
        text(s, x + Inches(0.42), ty + Inches(0.16), tw - Inches(0.62),
             BOT - ty - Inches(0.3), t, size=12, color=NAVY, spacing=1.15)
        x += tw + gap


def build_gambar(d, nomor):
    """Satu gambar besar melebar, catatan di bawahnya."""
    s = base(d, nomor)
    n = len(d.get("catatan", []))
    tinggi_ket = Inches(0.52) * n + Inches(0.2) if n else Emu(0)
    gh = BOT - TOP - tinggi_ket
    gambar(s, d["gambar"], ML, TOP, CW, gh, d.get("gambar_ket"))
    y = TOP + gh + Inches(0.2)
    for c in d.get("catatan", []):
        dot(s, ML, y + Inches(0.1))
        text(s, ML + Inches(0.28), y, CW - Inches(0.28), Inches(0.48), c,
             size=12, color=GREY, spacing=1.12)
        y += Inches(0.52)


def build_gambar_samping(d, nomor):
    """Butir di kiri, gambar di kanan."""
    s = base(d, nomor)
    gw = Inches(6.4)
    lebar_teks = CW - gw - Inches(0.5)
    bullet_list(s, d["butir"], TOP, BOT, kiri=ML, lebar=lebar_teks,
                size=13.5, sub_size=11.5)
    gambar(s, d["gambar"], W - MR - gw, TOP, gw, BOT - TOP,
           d.get("gambar_ket"))


def build_galeri_foto(d, nomor):
    """Dua foto bersebelahan dengan label hasil klasifikasinya."""
    s = base(d, nomor)
    n = len(d["foto"])
    gap = Inches(0.5)
    fw = int((CW - gap * (n - 1)) / n)
    fh = Inches(2.85)
    x = ML
    for berkas, label, warna_nama, ket in d["foto"]:
        c = WARNA[warna_nama]
        # Label diratakan selebar gambar yang benar-benar terpasang - foto
        # meter berbentuk tegak, jadi kalau labelnya selebar kolom akan
        # terlihat menggantung jauh dari fotonya.
        gx, _, nw, _ = gambar(s, berkas, x, TOP, fw, fh)
        rect(s, gx, TOP + fh + Inches(0.1), nw, Inches(0.4), fill=c,
             radius=0.12)
        text(s, gx, TOP + fh + Inches(0.1), nw, Inches(0.4), label,
             size=13, color=WHITE, bold=True, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE)
        text(s, x, TOP + fh + Inches(0.56), fw, Inches(0.38), ket,
             size=11.5, color=GREY, align=PP_ALIGN.CENTER, spacing=1.12)
        x += fw + gap
    y = TOP + fh + Inches(1.02)
    for c in d["catatan"]:
        dot(s, ML, y + Inches(0.09))
        text(s, ML + Inches(0.28), y, CW - Inches(0.28), Inches(0.44), c,
             size=12, color=GREY, spacing=1.1)
        y += Inches(0.46)


def build_manfaat(d, nomor):
    s = base(d, nomor)
    n = len(d["kolom"])
    gap = Inches(0.3)
    cwid = int((CW - gap * (n - 1)) / n)
    warna = [BLUE, GREEN, RED]
    x = ML
    tinggi = Inches(4.35)
    for i, (judul, isi) in enumerate(d["kolom"]):
        rect(s, x, TOP, cwid, tinggi, fill=LIGHT, line=LINE, radius=0.04)
        rect(s, x, TOP, cwid, Inches(0.54), fill=warna[i % 3])
        text(s, x, TOP, cwid, Inches(0.54), judul, size=12.5, color=WHITE,
             bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        yy = TOP + Inches(0.96)
        for b in isi:
            dot(s, x + Inches(0.24), yy + Inches(0.08), warna[i % 3],
                Inches(0.09))
            text(s, x + Inches(0.44), yy, cwid - Inches(0.7), Inches(0.8), b,
                 size=12.5, color=NAVY, spacing=1.18)
            yy += Inches(0.83)
        x += cwid + gap
    text(s, ML, TOP + tinggi + Inches(0.22), CW, Inches(0.7), d["catatan"],
         size=11.5, color=GREY, spacing=1.15)


def build_roadmap(d, nomor):
    s = base(d, nomor)
    n = len(d["tahap"])
    gap = Inches(0.34)
    cwid = int((CW - gap * (n - 1)) / n)
    warna = [GREEN, DGOLD, BLUE]
    kartu = Inches(4.3)
    isi_atas = TOP + Inches(0.9)
    tersedia = kartu - Inches(0.9) - Inches(0.2)
    x = ML
    for i, (judul, isi) in enumerate(d["tahap"]):
        rect(s, x, TOP, cwid, kartu, fill=LIGHT, line=LINE, radius=0.04)
        rect(s, x, TOP, cwid, Pt(6), fill=warna[i])
        text(s, x + Inches(0.24), TOP + Inches(0.26), cwid - Inches(0.48),
             Inches(0.32), judul, size=12, color=warna[i], bold=True)
        # Jatah tinggi dibagi rata, bukan ditebak dari panjang kalimat -
        # tebakan panjang meleset begitu kalimatnya membungkus dua baris.
        slot = min(Inches(1.25), int(tersedia / len(isi)))
        yy = isi_atas
        for b in isi:
            dot(s, x + Inches(0.24), yy + Inches(0.09), warna[i], Inches(0.09))
            text(s, x + Inches(0.46), yy, cwid - Inches(0.72), slot, b,
                 size=12.5, color=NAVY if i == 0 else GREY, spacing=1.18)
            yy += slot
        x += cwid + gap


def build_novelty(d, nomor):
    s = base(d, nomor)
    box = rect(s, ML, TOP, CW, Inches(1.2), fill=RGBColor(0xFF, 0xF8, 0xE6),
               line=GOLD, radius=0.04)
    tf, p, r = _style(box, 13.5, NAVY, False, PP_ALIGN.LEFT)
    r.text = d["payung"]
    r.font.italic = True
    p.line_spacing = 1.22
    tf.margin_left = tf.margin_right = Inches(0.24)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE

    y = TOP + Inches(1.46)
    n = len(d["pilar"])
    ih = int((BOT - y) / n)
    for kode, judul, ket, jenis in d["pilar"]:
        rect(s, ML, y + Inches(0.03), Inches(0.56), ih - Inches(0.14),
             fill=NAVY, radius=0.16)
        text(s, ML, y + Inches(0.03), Inches(0.56), ih - Inches(0.14), kode,
             size=13, color=GOLD, bold=True, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE)
        text(s, ML + Inches(0.76), y, Inches(9.2), Inches(0.3), judul,
             size=14, color=NAVY, bold=True)
        text(s, ML + Inches(0.76), y + Inches(0.29), Inches(9.2), Inches(0.3),
             ket, size=11.5, color=GREY)
        rect(s, W - MR - Inches(1.4), y + Inches(0.12), Inches(1.4),
             Inches(0.32), fill=WHITE, line=BLUE, radius=0.25)
        text(s, W - MR - Inches(1.4), y + Inches(0.12), Inches(1.4),
             Inches(0.32), jenis, size=9.5, color=BLUE, bold=True,
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        y += ih


def build_penutup(d, nomor):
    s = prs.slides.add_slide(BLANK)
    rect(s, Emu(0), Emu(0), W, H, fill=NAVY)
    rect(s, ML, Inches(1.5), Inches(1.4), Pt(5), fill=GOLD)
    text(s, ML, Inches(1.85), CW, Inches(0.9), d["judul"], size=42,
         color=WHITE, bold=True)
    text(s, ML, Inches(2.95), Inches(10.6), Inches(1.6), d["pesan"],
         size=16, color=PALE, spacing=1.35)
    y = Inches(4.85)
    for a in d["ajakan"]:
        dot(s, ML, y + Inches(0.1))
        text(s, ML + Inches(0.3), y, Inches(10), Inches(0.35), a, size=14,
             color=WHITE)
        y += Inches(0.46)
    text(s, W - MR - Inches(1), Inches(7.02), Inches(1), Inches(0.3),
         str(nomor), size=9, color=RGBColor(0x6B, 0x82, 0x99),
         align=PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = d.get("notes", "")


BUILDERS = {
    "cover": build_cover, "kartu": build_kartu, "kartu_teks": build_kartu_teks,
    "butir": build_butir, "daftar": build_daftar, "tabel": build_tabel,
    "alur": build_alur, "manfaat": build_manfaat, "roadmap": build_roadmap,
    "penutup": build_penutup, "novelty": build_novelty,
    "dua_kolom": build_dua_kolom, "masalah_tujuan": build_masalah_tujuan,
    "diagram_segmen": build_diagram_segmen, "gambar": build_gambar,
    "gambar_samping": build_gambar_samping, "galeri_foto": build_galeri_foto,
}


def untuk(deck):
    """Slide yang masuk ke berkas 'deck' ('ringkas' atau 'lengkap')."""
    return [d for d in SLIDES if d.get("hanya") in (None, deck)]


def bangun(deck, out):
    global prs, BLANK
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    BLANK = prs.slide_layouts[6]
    daftar = untuk(deck)
    for i, d in enumerate(daftar, 1):
        BUILDERS[d["kind"]](d, i)
    prs.save(out)
    print("  %-2d slide -> %s" % (len(daftar), os.path.basename(out)))
    return len(daftar)


def main():
    if not os.path.isdir(GAMBAR_DIR):
        print("Catatan: folder presentasi/gambar/ belum ada - slide bergambar "
              "akan memakai kotak penampung.\n"
              "         Jalankan dulu: python presentasi/siapkan_gambar.py\n")
    bangun("ringkas", OUT_RINGKAS)
    bangun("lengkap", OUT_LENGKAP)


if __name__ == "__main__":
    main()
