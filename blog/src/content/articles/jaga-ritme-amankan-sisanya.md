---
title: "Jaga Ritme, Amankan Sisanya: Jatah Harian yang Tidak Lagi Menyuruh Menghabiskan Uang"
description: "Jatah hari ini di Jatahku kini dihitung dari amplop harian saja, dipagari ritme normalmu, dan kelebihannya dicatat sebagai surplus untuk periode depan. Kenapa angkamu berubah, dan apa yang perlu kamu setel."
pubDate: 2026-10-23
category: update-fitur
author: Tim Jatahku
cover: /covers/jaga-ritme-amankan-sisanya.svg
featured: true
---

Kalau kamu membuka Beranda hari ini dan angka **Jatah hari ini** turun, atau kartu **Sisa bebas** tiba-tiba bertuliskan "dana harian" dan "Surplus +Rp…", itu bukan salah hitung. Kami mengubah cara Jatahku menghitung jatah harian, untuk semua akun. Artikel ini menjelaskan kenapa, apa yang berubah, dan satu pengaturan kecil yang sebaiknya kamu lakukan.

## Masalahnya: rumus lama menyuruh kamu menghabiskan uang

Rumus lama sederhana: **sisa bebas ÷ sisa hari**. Di awal periode rumus ini masuk akal. Tapi di akhir periode ia berbalik melawan kamu.

Contoh nyata dari salah satu akun kami, 3 hari sebelum gajian. Ada pemasukan tambahan Rp7,6 juta di luar gaji, dialokasikan ke beberapa amplop, yang terbesar ke **Pendidikan** (SPP bulan depan) dan **Tagihan Hutang**. Beranda langsung menampilkan:

> Jatah hari ini: Rp116.000 / **Rp2.128.800**
> Sisa bebas: Rp8,19 jt untuk 3 hari · **aman Rp2,73 jt/hari**

Secara matematika benar. Secara perilaku, berbahaya. Dashboard seolah bilang "kamu boleh jajan Rp2 juta sehari". Kalau benar-benar diikuti, uang SPP habis sebelum tagihannya datang, dan periode berikutnya dimulai dari nol.

Ada tiga cacat di rumus lama:

1. **Semua amplop dicampur.** Uang SPP dan cicilan dianggap uang bebas yang boleh habis dalam 3 hari.
2. **Pembaginya mengecil di ujung periode.** Uang yang masuk di H-3 dibagi 3, bukan 30. Rp1,75 juta tambahan untuk Makan menjadi +Rp490 ribu per hari, padahal kalau dibagi ke seluruh periode hanya +Rp58 ribu per hari.
3. **Tidak ada rem dari kebiasaan nyata.** Ritme makan dan transport orang itu sebenarnya sekitar Rp160 ribu per hari. Angka Rp2 juta tidak punya hubungan dengan hidupnya.

## Filosofi baru: jaga ritme, amankan sisanya

Prinsip yang sekarang dipakai Jatahku:

> Jatah harian menjaga ritme belanja normalmu, bukan menghabiskan saldo tepat di hari terakhir. Sisa hari boleh **menekan** jatah ke bawah saat uang menipis, tetapi tidak boleh **mendongkrak** jatah saat uang berlebih. Kelebihannya adalah surplus yang dibawa ke periode depan.

Dengan data yang sama, Beranda orang tadi sekarang menampilkan:

> Jatah hari ini: Rp116.000 / **Rp224.600** · ritme Rp161 rb/hari
> Sisa bebas: **Rp2,39 jt** dana harian, 3 hari · jaga Rp224 rb/hari · dicadangkan Rp5,8 jt
> Chip: **Surplus +Rp1,65 jt**

Pesan yang tertangkap berubah dari "boleh jajan Rp2 juta" menjadi "jaga Rp225 ribu per hari, dan kamu membawa Rp1,65 juta ke bulan depan".

## Apa yang berubah di layar

### 1. Amplop harian dan amplop bulanan dipisah

Jatah harian sekarang hanya dihitung dari **amplop harian**: Makan, Transport, Jajan, dan sejenisnya. Amplop untuk pembayaran bulanan seperti SPP, cicilan, listrik, atau internet masuk kelompok **bulanan**. Saldonya tidak pernah dibagi ke hari; di kartu Sisa bebas ia tampil sebagai **"dicadangkan"**.

Amplop berjenis cicilan otomatis dianggap bulanan. Untuk amplop lain, Jatahku membaca **jenis grup** amplopnya. Ini pengaturan kecil yang perlu kamu lakukan sekali (lihat bagian berikutnya).

### 2. Jatah dipagari ritme ideal

Jatah hari ini sekarang mengambil nilai yang **lebih kecil** dari dua angka:

- sisa dana harian ÷ sisa hari (rumus lama), dan
- **total dana harian periode ini ÷ jumlah hari periode** (pagar baru).

Pagar ini yang membuat uang masuk di tengah periode dibagi rata ke seluruh periode. Dari top-up di H-3, kira-kira 27/30 bagiannya otomatis diamankan sebagai surplus. Sebaliknya, kalau uangmu menipis, rumus lama tetap menang dan jatahmu turun seperti biasa. Pagar hanya menahan ke atas, tidak pernah menahan ke bawah.

Untuk kamu yang pendapatannya harian atau mingguan, pagar ini tidak dipakai, karena danamu memang masuk bertahap.

### 3. Surplus, bukan "aman per hari"

Kartu Sisa bebas tidak lagi bertuliskan "aman Rp2,73 jt/hari". Angka utamanya kini **dana harian**, keterangannya **"jaga Rp…/hari"**, dan kalau kamu di bawah pagar, chip-nya **"Surplus +Rp…"** dengan tombol **Setor ke tabungan**. Surplus itu nyata: saldo amplop yang tidak terpakai memang dibawa utuh ke periode berikutnya (rollover), jadi menjaga ritme hari ini langsung terasa di bulan depan.

### 4. Ritme biasamu ikut ditampilkan

Di kartu Jatah hari ini ada catatan "ritme Rp…/hari", yaitu rata-rata belanja harianmu di periode ini. Kalau belanja hari ini jauh di atas ritme itu padahal masih dalam jatah, AI Advisor memberi tahu lewat chip "1,5× ritme biasa". Ritme ini sengaja hanya pembanding, bukan pemotong jatah: kami tidak ingin orang yang sedang hemat justru dihukum dengan jatah yang makin kecil.

### 5. Belanja besar sekali waktu langsung memotong jatah hari itu

Sebelumnya pembelian besar seperti kulkas tidak mengubah jatah hari itu, sehingga chip masih bisa bilang "Sisa Rp300 rb hari ini" setelah Rp2 juta keluar. Sekarang jatah hari itu langsung turun, sama seperti saat kamu mencocokkan saldo.

## Satu pengaturan yang sebaiknya kamu lakukan

Buka halaman **Amplop**. Di kepala setiap grup ada pilihan baru: **Otomatis / Harian / Bulanan**.

- Setel grup yang berisi SPP, cicilan, listrik, internet, dan pembayaran bulanan lain ke **Bulanan**.
- Biarkan grup Makan, Transport, dan jajan di **Harian** (atau Otomatis).

Begitu disetel, jatah harianmu dihitung dari amplop harian saja, dan saldo amplop bulanan tampil sebagai "dicadangkan". Kalau sebuah amplop polanya bulanan tetapi masih di grup harian, AI Advisor akan menyarankannya di kartu Beranda: "{amplop} sepertinya pengeluaran bulanan".

Amplop tanpa grup ikut aturan otomatis: amplop cicilan dianggap bulanan, selebihnya harian.

## Pertanyaan yang mungkin muncul

**Kenapa jatahku turun padahal uangku bertambah?**
Karena uang tambahan itu dibagi ke seluruh periode, bukan ke sisa hari. Kelebihannya tidak hilang; lihat chip "Surplus +Rp…" dan ia akan menjadi saldo awal periode berikutnya.

**Apakah ini berlaku di chat dan Telegram juga?**
Ya. Semua angka datang dari satu mesin hitung, jadi `/status`, pertanyaan "sisa jatah", dan Beranda menampilkan angka yang sama, termasuk baris "dicadangkan" dan "surplus".

**Bagaimana kalau aku memang ingin memakai surplusnya?**
Tidak ada yang diblokir. Jatahku adalah cermin, bukan penjaga gerbang. Jatah hanya memberi tahu ritme yang sehat; keputusannya tetap di tanganmu.

Detail rumusnya untuk yang ingin tahu: dana harian periode ini, pembagi hari periode, pembulatan ke bawah Rp100, dan aturan pembandingnya ada di dokumentasi AI Advisor di repositori Jatahku.
