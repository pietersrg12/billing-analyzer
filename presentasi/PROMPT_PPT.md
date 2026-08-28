# Prompt Pembuatan Ulang PPT SIMBA - Bahasa Awam

Dipakai untuk menulis ulang presentasi supaya bisa dimengerti atasan yang tidak
mengerti listrik, tidak mengerti billing, dan tidak mengerti komputer.

Isi berkas ini:

- **Bagian 0** - bahan bersama. Aturan bahasa, kamus ganti kata, lembar fakta.
- **Bagian A** - prompt untuk Claude Code, menulis ulang naskah di `buat_ppt.py`.
- **Bagian B** - prompt tempel untuk Gamma, Copilot, atau ChatGPT.

---

# BAGIAN 0 - BAHAN BERSAMA

Bagian ini dipakai oleh Bagian A maupun Bagian B.

## 0.1 Siapa yang mendengarkan

Manajemen PLN yang bukan orang teknis. Anggap mereka:

- tidak tahu apa itu DPM, stand, jam nyala, cabut/pasang, rollover.
- tidak tertarik pada nama teknologi.
- hanya ingin tahu enam hal: apa masalahnya, berapa besar, apa yang sudah dibuat,
  buktinya mana, apa untungnya, dan apa yang belum selesai.

Patokan: **kalau kalimat itu tidak akan dimengerti oleh orang yang baru pertama kali
mendengar soal tagihan listrik, kalimat itu salah.**

## 0.2 Aturan bahasa (wajib, bisa dicek satu per satu)

1. Satu kalimat berisi satu ide. Maksimal **15 kata**.
2. Kalimat aktif dengan pelaku di depan. Tulis "Aplikasi ini memeriksa...", bukan
   "Dilakukan pemeriksaan terhadap...".
3. **Dilarang** memakai tanda pisah panjang, titik koma, dan tanda kurung untuk
   menyelipkan penjelasan. Pecah jadi kalimat baru.
4. Kata "yang" maksimal satu kali per kalimat.
5. Jangan memulai kalimat dengan kata benda bentukan: Menyatukan, Membangun,
   Menghasilkan, Melakukan, Pemberian, Penyajian, Pembandingan.
6. Setiap istilah teknis yang terpaksa dipakai harus langsung dijelaskan sekali
   dengan kalimat pendek berawalan "Artinya,".
7. Angka besar selalu diberi pembanding sehari-hari.
   Contoh: "2.247 dari 19.915 pelanggan. Kira-kira 1 dari 9."
8. Judul slide maksimal **8 kata**, dan harus bisa dimengerti tanpa membaca isinya.
9. Maksimal **4 butir** per slide. Satu butir maksimal **12 kata**.
10. Catatan pembicara ditulis seperti orang berbicara, bukan seperti orang menulis
    laporan.

## 0.3 Kamus ganti kata (wajib)

| Jangan pakai | Pakai |
|---|---|
| anomali | kejanggalan, pemakaian tidak wajar |
| deteksi anomali | mencari tagihan yang janggal |
| validasi, verifikasi | memeriksa, mengecek |
| klasifikasi foto | memilah foto |
| computer vision, model YOLOv8 | komputer yang dilatih mengenali gambar |
| baseline statistik | pemakaian normal pelanggan itu sendiri |
| median 6 bulan | pemakaian tengah selama enam bulan terakhir |
| ambang, threshold | batas |
| aturan berjenjang | aturan bertingkat, diperiksa berurutan dari atas |
| artefak, output, keluaran | hasil, berkas, file |
| terprioritaskan | sudah diurutkan dari yang paling penting |
| dapat ditindaklanjuti | bisa langsung dikerjakan |
| kegentingan | seberapa mendesak |
| replikabilitas | gampang dipakai unit lain |
| novelty | apa yang baru |
| eksisting | yang dipakai sekarang |
| implementasi | penerapan |
| dua segmen | dua bagian, sebelum meter dicabut dan sesudah meter baru dipasang |
| stand | angka yang tertera di meteran |
| DPM | daftar tagihan listrik satu bulan dari sistem |
| jam nyala | ukuran wajar atau tidaknya pemakaian dibanding daya terpasang |
| rollover | meteran habis angkanya lalu kembali ke nol |
| paralel, pipelined | dikerjakan bersamaan |
| degrade gracefully | kalau satu bagian mati, sisanya tetap jalan |
| unggah ke sistem | dikirim ke sistem |

## 0.4 Lembar fakta terkunci (JANGAN diubah, JANGAN dikarang tambahan)

Semua angka berasal dari hitungan nyata atas DPM periode Agustus 2026.

- 19.915 pelanggan diperiksa dalam satu file.
- 2.247 pelanggan perlu diperiksa lebih lanjut. Setara 11,3 persen.
- 17.668 pelanggan normal. 11 pelanggan baru dan belum punya riwayat.
- Tujuh jenis kejanggalan dan jumlahnya:
  Stand Minus 699, Stand Tidak Wajar 574, Meter Macet 95, Lebih dari 720 Jam Nyala 117,
  Kenaikan 319, Trend Naik 52, Penurunan 380.
- Aturan diperiksa berurutan dan berhenti di yang pertama cocok. Tidak ada pelanggan
  terhitung dua kali.
- Penggantian meter bulan itu 57. Yang angkanya tidak konsisten 19.
- Selisih menumpuk 1.061.089 kWh. Sepuluh di antaranya tepat 100.000 kWh.
- Contoh kasus nyata: meteran sama sekali tidak berputar, angka awal dan akhir
  sama-sama 11.456, tetapi tagihan terbit 100.000 kWh.
- Lembar koreksi berisi 2.236 baris. 827 di antaranya sudah terisi saran otomatis:
  679 rumah kosong, 128 dibatasi 720 jam nyala, 20 diganti rata-rata karena fotonya
  bukan meteran.
- Ada 9 pilihan alasan koreksi. Satu pelanggan hanya boleh punya satu koreksi.
- Foto meteran tiga bulan terakhir ikut menempel pada baris yang perlu diperiksa.
- Foto hanya diunduh untuk 2.247 pelanggan bermasalah, bukan semua.
- Foto yang sudah diunduh dipakai lagi bulan berikutnya.
- Pembacaan angka meteran langsung dari foto **belum aktif**. Modelnya sudah ada,
  ketelitiannya masih dikalibrasi. Fakta ini wajib disebut apa adanya.

Bagian yang belum bisa diukur tetap ditulis sebagai isian `[__]`. Jangan diisi
angka karangan:

- Nama, jabatan, unit, periode, dan kontak penyaji.
- Jam-orang per bulan sebelum dan sesudah memakai aplikasi.

Larangan keras: jangan menyebut nilai rupiah, persentase penghematan, atau jumlah
pelanggan yang tidak ada di daftar ini.

## 0.5 Satu hal yang harus jelas sejak slide pertama

Nama karya ini SIMBA. Aplikasi SIMBA milik PLN adalah aplikasi lain. Aplikasi itu
menjadi salah satu sumber fotonya. Karya ini **bukan** bagian dari aplikasi tersebut.
Sebutkan sekali di slide pembuka dengan kalimat pendek.

## 0.6 Alur cerita baru (14 slide, versi 15 menit)

Struktur lama bergaya lomba dibuang dari versi tampil. Ganti dengan alur ini.

| # | Slide | Inti yang harus tersampaikan |
|---|---|---|
| 1 | Sampul | Nama karya, satu kalimat isinya, catatan beda dengan SIMBA PLN, identitas penyaji |
| 2 | Empat angka besar | 19.915 diperiksa, 2.247 janggal, 2.236 siap dikoreksi, 19 salah ganti meter |
| 3 | Masalahnya | Tiap bulan 20.000 tagihan. Yang sempat diperiksa hanya sebagian |
| 4 | Kenapa tidak bisa diperiksa semua | Bukti ada di tiga tempat. Yang tersaring hanya yang diberi kode petugas |
| 5 | Apa yang dibuat | Satu tombol, satu file hasil. Pakai gambar jendela aplikasi |
| 6 | Cara kerjanya | Sembilan tahap teknis dipadatkan jadi empat langkah yang bisa dibayangkan |
| 7 | Apa saja yang dicari | Tujuh jenis kejanggalan dan jumlahnya. Tabel sederhana |
| 8 | Temuan paling penting | Meteran tidak berputar tapi tagihan 100.000 kWh. Pakai diagram |
| 9 | Buktinya | Tangkapan layar lembar CABUT_PASANG |
| 10 | Foto meteran ikut menempel | Komputer memilah foto yang bukan meteran lebih dulu |
| 11 | Hasilnya bukan laporan | Berkas koreksi yang tinggal dipilih lalu dikirim |
| 12 | Sebelum dan sesudah | Tabel enam baris. Baris ganti meter yang paling kuat |
| 13 | Sudah bisa dipakai | Cara memasang, cara memindah ke unit lain, dan yang belum selesai |
| 14 | Penutup | Satu kalimat penutup dan ajakan uji coba |

Slide 8 adalah puncak cerita. Beri porsi bicara paling panjang di situ.

## 0.7 Kriteria selesai

Naskah dianggap selesai kalau semua ini benar:

1. Tidak ada kalimat lebih dari 15 kata.
2. Tidak ada satu pun kata dari kolom kiri kamus 0.3.
3. Tidak ada tanda pisah panjang dan tidak ada titik koma di seluruh naskah.
4. Semua angka cocok dengan lembar fakta 0.4. Tidak ada angka baru.
5. Setiap judul slide maksimal 8 kata.
6. Fakta "pembacaan angka dari foto belum aktif" tetap ada.
7. Semua isian `[__]` masih berupa isian.

---

# BAGIAN A - PROMPT UNTUK CLAUDE CODE

Tempel mulai dari garis bawah ini ke sesi Claude Code baru di folder proyek ini.

---

Tulis ulang naskah presentasi di `presentasi/buat_ppt.py` supaya bisa dimengerti
atasan yang bukan orang teknis. Baca dulu Bagian 0 di `presentasi/PROMPT_PPT.md`.
Semua aturan bahasa, kamus ganti kata, lembar fakta, alur 14 slide, dan kriteria
selesai di sana berlaku penuh dan tidak boleh dilanggar.

**Batas pekerjaan:**

- Ubah **hanya** isi list `SLIDES` di `presentasi/buat_ppt.py`, kira-kira baris 66
  sampai 619, dan docstring di atasnya bila jumlah slidenya berubah.
- **Jangan sentuh** kode layout mulai baris 621 ke bawah. Palet warna, ukuran huruf,
  margin, dan fungsi `build_*` biarkan apa adanya.
- Pakai `kind` yang sudah tersedia: `cover`, `kartu`, `kartu_teks`, `butir`, `daftar`,
  `masalah_tujuan`, `dua_kolom`, `tabel`, `alur`, `diagram_segmen`, `gambar`,
  `gambar_samping`, `galeri_foto`, `manfaat`, `roadmap`, `novelty`, `penutup`.
  Tambah fungsi `build_*` baru hanya kalau benar-benar tidak ada yang cocok. Kalau
  sampai perlu, sebutkan dulu alasannya sebelum menulis.
- Pakai gambar yang sudah ada di `presentasi/gambar/`: `app_utama.png`,
  `app_progres.png`, `app_pengaturan.png`, `excel_cabut_pasang.png`,
  `excel_koreksi_stand.png`, `excel_baris_foto.png`, `foto_kwh_meter.png`,
  `foto_bukan_kwh.png`. Jangan membuat gambar baru.

**Pembagian dua versi:**

- 14 slide alur baru di Bagian 0.6 adalah versi tampil. Beri `hanya="ringkas"` pada
  slide yang khusus versi ini.
- Versi lengkap adalah cadangan tanya jawab. Boleh menyimpan slide bergaya lomba
  seperti rumusan masalah, tujuan, tabel pembanding, dan daftar apa yang baru.
  Beri `hanya="lengkap"`. Bahasanya tetap mengikuti aturan yang sama.
- Slide tanpa kunci `hanya` masuk ke dua-duanya.

**Langkah kerja:**

1. Tulis ulang list `SLIDES`.
   Verifikasi: baca sendiri satu per satu memakai daftar 0.7. Laporkan hasil
   pengecekan tiap butir.
2. Jalankan `python presentasi/buat_ppt.py`.
   Verifikasi: perintah selesai tanpa error, dan dua file `.pptx` di `presentasi/`
   tanggalnya berubah.
   Catatan: kalau muncul error izin akses, berarti file PPT sedang dibuka di
   PowerPoint. Minta saya menutupnya dulu.
3. Laporkan jumlah slide versi ringkas dan versi lengkap.
   Verifikasi: versi ringkas berisi 14 slide.

**Kalau ada yang tidak jelas, tanya dulu. Jangan mengarang angka. Jangan menambah
klaim manfaat yang tidak ada di lembar fakta.**

---

# BAGIAN B - PROMPT TEMPEL UNTUK AI PEMBUAT SLIDE

Untuk Gamma, Copilot, ChatGPT, atau sejenisnya. Berdiri sendiri, tidak perlu akses
ke folder proyek. Tempel mulai dari garis bawah ini, lalu tempel juga seluruh
Bagian 0 di bawahnya.

---

Buatkan presentasi 14 slide dalam bahasa Indonesia.

**Judul:** SIMBA, Sistem Monitoring Baca Meter.
**Pembicara:** pegawai PLN yang membuat sendiri aplikasi ini.
**Pendengar:** manajemen PLN yang bukan orang teknis.
**Durasi:** 15 menit.

Aturan bahasa, kamus ganti kata, lembar fakta yang tidak boleh diubah, alur 14
slide, dan kriteria selesai ada di bagian bawah pesan ini. Ikuti semuanya.

Untuk setiap slide, tuliskan:

1. Judul slide, maksimal 8 kata.
2. Isi slide, maksimal 4 butir, satu butir maksimal 12 kata.
3. Catatan pembicara, 2 sampai 4 kalimat, ditulis seperti orang berbicara.
4. Saran gambar atau diagram, satu kalimat.

Ketentuan tambahan:

- Jangan memakai angka yang tidak ada di lembar fakta.
- Jangan menyebut nilai rupiah atau persentase penghematan.
- Bagian bertanda `[__]` biarkan kosong sebagai isian.
- Sebelum menutup jawaban, periksa sendiri naskahnya memakai daftar kriteria
  selesai, lalu tulis hasil pemeriksaannya.

Setelah baris ini, tempelkan seluruh isi BAGIAN 0.
