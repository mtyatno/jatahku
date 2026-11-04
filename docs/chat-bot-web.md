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
              ──POST /bot/chat/bukti   {items: [{item_id, message_id}]}──▶ web_adapter.run_bukti
                                                              │
                         handler app/bot/* (handle_message, /status, callback t_, fshift:, …)
                                                              │
              ◀──────────── {"ops": [message | edit | buttons | toast]} ──┘
                            (/bukti juga: "pending": [item_id yang masih dibaca])
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
8 MB), lalu dijalankan lewat `handle_non_text` → `receipt_cmd.handle_receipt_document`
— alur yang sama dengan kirim foto ke @JatahkuBot, yaitu **Kotak Struk** (sumber
`web_chat`, lihat [`kotak-struk.md`](kotak-struk.md)): pilih amplop lewat tombol,
"Nominal salah", feedback belajar. **Tidak ada kuota scan** (dihapus untuk semua
paket); batasnya hanya batas intake Kotak Struk (30 bukti/jam per user dan maks 20
yang belum selesai, gabungan semua kanal). Foto JPEG masuk sebagai `photo`, format
lain sebagai `document`. Kirim ulang
dengan `client_id` yang sama tidak diproses dua kali (balasan yang sama dikembalikan),
dan file yang sama selagi masih dibaca atau menunggu dikembalikan sebagai item yang
sama. Riwayat lokal hanya menyimpan pratinjau kecil (±2–5 KB), bukan fotonya.

**Bukti yang belum selesai dibaca dalam 10 detik** (OCR pertama sesudah API restart,
foto yang jatuh ke LLM cadangan, worker sedang memproses bukti lain) dijawab
"⏳ Masih dibaca, nanti kukabari di sini." — padanan "nanti kukabari" di Telegram, tetapi
hasilnya **ditarik panel, bukan didorong worker**, karena server tidak menyimpan riwayat
chat web (`send_ready_message` hanya untuk Telegram; item chat web tidak punya `notify`):

- op `edit` gelembung itu membawa `item` (id item Kotak Struk) dan `pending: true`; riwayat
  lokal menyimpan keduanya (`lib/chatHistory.js`), jadi bertahan walau app ditutup.
- Selagi panel terbuka, `ChatPanel` memanggil `POST /bot/chat/bukti` `{items: [{item_id,
  message_id}]}` dengan jeda 3→5→8→13→20→30 dtk (aturan di `lib/chatPending.js`), juga segera
  saat panel dibuka lagi dan saat app kembali tampil. Jawabannya `{ops, pending}`:
  `run_bukti` → `receipt_cmd.reply_item_result` merender hasil item (teks dan tombol yang
  sama persis dengan Telegram, sesi tombol `txn:{key}` baru, tombol dicatat seperti pesan bot
  lain) sebagai op `edit` untuk pesan yang sama; item yang masih dibaca masuk `pending` dan
  gelembungnya tidak disentuh. Panel ditutup → berhenti bertanya; dibuka lagi → tanya lagi.
- Hasil yang sudah selesai di tempat lain dikabari tanpa tombol catat: `tercatat` → "✅ Bukti
  ini sudah tercatat …", `dilewati` → "❌ Dilewati.", `kedaluwarsa` (QRIS/transfer) → "⚠️ Bukti
  ini sudah kedaluwarsa, …", `gagal` → galatnya. Item yang tidak ada atau bukan milik user →
  "😕 Bukti ini sudah tidak ada. Kirim ulang fotonya." tanpa `item`, jadi panel berhenti
  bertanya. Galat merender satu item dicatat di log dan item itu dikembalikan sebagai
  `pending` (ditanya lagi nanti), supaya hasilnya tidak hilang dari chat.
- **Tombol basi disegarkan.** Sesi tombol bot hanya 10 menit (`TXN_TTL`). Riwayat lokal
  mencatat `renderedAt`; saat panel dibuka atau app kembali tampil, gelembung bukti yang masih
  bertombol dan dirender ≥ 9 menit lalu ikut dikirim ke `/bukti` dan dirender ulang dengan sesi
  baru — tanpa itu, ketukan sesudah pergi sebentar dijawab "⏰ Session expired. Kirim ulang."
  Catatan atau jawaban tanggal yang sempat diberikan pada sesi lama ikut hilang (sesinya memang
  sudah habis); pesan dirender dari status item saat ini.
- Bukti yang sama dikirim lagi selagi dibaca dijawab "⏳ Bukti ini sudah dikirim tadi dan masih
  dibaca. Hasilnya nanti di sini." dengan `item`/`pending` juga (riwayat chat web per perangkat,
  pesan pertama bisa ada di HP lain); keduanya mendapat hasil, pencatatan tetap sekali (item
  `tercatat` tidak bisa dicatat lagi lewat tombol pesan lainnya).
- Hasil yang datang lewat `/bukti` menggulir daftar ke bawah hanya bila user sedang di paling
  bawah (edit biasa tidak menggulir, seperti Telegram). Selama menunggu, di bawah gelembung
  tampil "Hasilnya muncul di sini begitu selesai dibaca".

**Route ini tetap khusus gambar**: PDF ditolak 415 ("Format foto tidak didukung. Pakai
JPG, PNG, atau WebP."). Bot Telegram sudah menerima PDF lewat alur yang sama; dari web,
PDF masuk lewat tombol **PDF** di form Catat (`/transactions/scan-receipt`) dan lewat
Web Share Target PWA (halaman `/bagikan`, Bagian B "Bagikan ke Jatahku"), keduanya hanya
saat saklar `receipt_inbox` menyala; menu Bagikan Android menunggu `share_target` di
manifest (lihat [`kotak-struk.md`](kotak-struk.md) bagian "Web dan PWA").

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
- Bukti PDF di chat web (route foto tetap khusus gambar; PDF dari web lewat form Catat dan
  `/bagikan`). Bukti dari chat yang selesai dibaca belakangan diambil panel chat sendiri (lihat
  "Foto struk"); saat saklar `receipt_inbox` menyala, item yang sama juga dihitung banner "Bukti
  menunggu" dan tampil sebagai kartu di `/bagikan` (Bagian B "Bagikan ke Jatahku").
- Hasil bukti yang selesai saat panel chat tertutup baru terlihat saat chat dibuka lagi; belum ada
  lencana di tombol chat atau notifikasi dalam aplikasi untuk itu.
