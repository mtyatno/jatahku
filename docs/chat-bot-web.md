# Chat bot di webapp (PWA)

User webapp bisa memakai @JatahkuBot tanpa Telegram: panel chat di PWA
(tombol chat di header, opsi **Chat bot** di FAB, atau `?chat=1` / shortcut
PWA "Chat bot"). Otaknya **handler bot Telegram yang sama** — tidak ada logika
kedua yang harus dirawat.

**Mobile = bottom sheet yang bisa dibuka-tutup dengan jempol:**
- buka: tombol chat di samping FAB (sekali ketuk); FAB tidak lagi punya opsi chat;
- tinggi awal **setengah layar HP yang sedang dipakai** (dihitung dari tinggi
  layar, jadi menyesuaikan HP pendek/tinggi); tarik pegangan ke atas atau ketuk
  pegangan → penuh, tarik/ketuk lagi → setengah (`lib/sheetGesture.js`);
- keyboard terbuka → sheet otomatis penuh tepat di atas keyboard (Visual
  Viewport API), kembali setengah saat keyboard ditutup;
- tutup: tombol ⌄ di kiri kotak ketik, tarik ke bawah dari setengah, ketuk
  latar redup, atau tombol/gestur Back Android (membuka chat menambah satu
  entri riwayat; menutup lewat tombol mengambilnya kembali).

Desktop: panel samping di bawah header, ditutup dengan X.

## Alur

```
ChatPanel.jsx ──POST /bot/chat/message {text, client_id}──▶ web_adapter.run_message
              ──POST /bot/chat/action  {message_id, data}──▶ web_adapter.run_action
              ──POST /bot/chat/photo   (image, client_id)──▶ web_adapter.run_photo
                                                              │
                         handler app/bot/* (handle_message, /status, callback t_, fshift:, …)
                                                              │
              ◀──────────── {"ops": [message | edit | buttons | toast]} ──┘
```

- `app/bot/web_adapter.py` — objek pengganti `Update`/`Message`/`CallbackQuery`
  (hanya API yang dipakai handler: `reply_text`, `edit_message_text`, `answer`,
  `effective_user`, `context.args`). Balasan dikumpulkan sebagai ops JSON;
  `format` = parse_mode Telegram (`html` / `markdown` / `plain`).
- `app/bot/channel.py` — satu-satunya tempat yang tahu beda kanal:
  - id chat web `web:<user_uuid>`; `find_chat_user` mengenali keduanya, id
    `web:` hanya berlaku di dalam `web_channel()` dan akun web tidak pernah
    dibuat otomatis;
  - `txn_source()` → transaksi dari chat web tercatat `webapp`.
- `bot_commands()` / `bot_callbacks()` di `handlers.py` — daftar perintah &
  tombol bersama Telegram dan web. **Perintah/tombol baru cukup didaftarkan di
  sana** dan otomatis tersedia di kedua kanal.
- Jawaban angka ("sisa", `/status`, limit harian, kapan habis, pengeluaran hari
  ini, "kenapa …", "aman beli …") dan ringkasan harian/mingguan untuk user di
  flag `advisor_v2_users` disusun `app/bot/advisor_cmd.py` →
  `app/services/advisor/chat.py` (metrics + render AI Advisor, angka sama dengan
  Beranda); user lain masih mendapat jawaban lama sampai flag `*` (S10).
- S17: "tagihan bulan ini", "target {nama}", `/tanya` (tombol `tanya:<intent>`),
  `/tagihan`, `/target`, dan tombol "ganti amplop" untuk "aman beli" (`sim:{jumlah}:{amplop}`).
  Menu perintah Telegram = `help_cmd.BOT_COMMANDS`. Chip di bawah chat web per halaman:
  `lib/chatChips.js` (chip dari insight tetap didahulukan).
- Perintah akun khusus Telegram (`/link`, `/unlink`, `/webapp`, tombol
  `merge_`/`unlink_`) tidak dijalankan di web; `/start` mengabaikan deep link.
- Teks yang berbeda per kanal memakai `is_web()` (mis. `/help`, ajakan setup,
  petunjuk `/template` & `/amplop_baru`).

## Tampilan balasan

Bot menulis teks yang sama untuk Telegram dan web: emoji, bar `▰▰▰▱▱▱`, dan
garis `────`. Di web, `components/ChatText.jsx` (+ `lib/chatIcons.js`) mengubahnya
menjadi bahasa visual aplikasi: emoji dekoratif → ikon Phosphor (✅ ⚠️ 💡 📊 …),
emoji amplop → ikon kategori yang sama dengan halaman Amplop, 🟢🟡🔴⚪ → titik
status, bar teks → bar pemakaian sungguhan, garis → pemisah tipis. Emoji yang
tidak dipetakan (wajah, keluarga) tetap tampil sebagai emoji. Emoji baru di
balasan bot cukup ditambahkan ke `CHAT_EMOJI`. Telegram tetap memakai emoji
(set emoji Telegram sendiri) dengan bar `▰▱`.

## Foto struk

Tombol **Foto** (kamera langsung) dan **Galeri** (pemilih berkas), di samping
Suara, mengirim foto ke `POST /bot/chat/photo`. Keduanya komponen bersama
`ReceiptInput`, sama dengan form Catat. Selama foto dikirim, gelembung foto
menampilkan tahapnya ("Mengunggah foto… xx%", lalu "Membaca struk…"); unggahan
lewat XHR (`api.uploadForm`) dengan batas waktu 60 detik.
Foto dikompres di HP dulu (`lib/receiptImage.js`, sama dengan tombol Foto/Galeri
di form), divalidasi sama dengan `/transactions/scan-receipt` (JPG/PNG/WebP, maks
8 MB), lalu dijalankan lewat `handle_non_text` → `receipt_cmd.handle_receipt_photo`
— alur yang sama dengan kirim foto ke @JatahkuBot: kuota scan bulanan, batas per
jam, pilih amplop lewat tombol, "Nominal salah", feedback belajar. Foto JPEG
masuk sebagai `photo`, format lain sebagai `document`. Kirim ulang dengan
`client_id` yang sama tidak memindai dua kali (kuota aman). Riwayat lokal hanya
menyimpan pratinjau kecil (±2–5 KB), bukan fotonya.

## Keamanan

- **Tombol**: setiap tombol yang dikirim ke user dicatat per pesan di Redis
  (`webchat:btn:<user_id>:<msg_id>`, 3 hari). Tombol hanya diproses bila
  tercatat untuk pesan itu — jaminan yang sama dengan Telegram (callback_data
  hanya datang dari tombol yang benar-benar dikirim bot). Redis mati → ditolak.
- **Satu tombol sekali proses**: `webchat:lock:<user_id>:<msg_id>` (30 dtk)
  mencegah dua ketukan bersamaan (dua tab/perangkat) mencatat dua kali.
- **Kirim ulang aman**: webapp mengirim `client_id` (id pesan lokal); hasilnya
  disimpan 10 menit di `webchat:req:<user_id>:<client_id>`, jadi pesan yang
  dikirim ulang setelah koneksi putus mengembalikan ops yang sama.
- **Kontrak visibilitas household**: amplop personal anggota lain tidak bisa
  jadi tujuan pengeluaran (`find_best_envelope`), langganannya tidak tampil di
  `/langganan` / `/hapus_langganan`, dan tombol `delrec_`/`recpay_`/`recskip_`/
  `recstop_`/`lock_`/`cool_` mengecek kepemilikan di handler (berlaku juga
  untuk Telegram).
- Frontend tidak pernah merender HTML mentah: `chatFormat.js` mengubah
  HTML/Markdown Telegram menjadi node React; tautan hanya http(s).
- Rate limit 60/menit per token, ditambah batas 30 pesan/menit milik bot.

## Riwayat

Disimpan di `localStorage` per user (`jatahku_chat_<user_id>`, 100 pesan
terakhir), seperti riwayat chat Telegram di HP. Dihapus saat logout atau lewat
tombol sapu di panel. Server tidak menyimpan riwayat.

## Deploy

Tidak ada migrasi DB dan dependensi baru. Endpoint baru di
`api.jatahku.com/bot/chat/*` — lewat proxy Nginx yang sama dengan route API
lain. Setelah deploy: buka webapp, ketuk ikon chat, kirim `kopi 35k` dan
`/status`, lalu tekan salah satu tombol pilihan amplop.

## Belum ada (follow-up)

- Pesan yang dikirim bot atas inisiatif sendiri (pengingat tagihan langganan,
  check-in harian, nanti "Sepadan?" Pikir-Pikir) ke chat web — sekarang hanya
  lewat Telegram.
- Foto struk di chat (setelah PR scan struk di-merge).
