# Chat bot di webapp (PWA)

User webapp bisa memakai @JatahkuBot tanpa Telegram: panel chat di PWA
(tombol chat di header, opsi **Chat bot** di FAB, atau `?chat=1` / shortcut
PWA "Chat bot"). Otaknya **handler bot Telegram yang sama** — tidak ada logika
kedua yang harus dirawat.

**Mobile = bottom sheet yang bisa dibuka-tutup dengan jempol:**
- buka: tombol chat di samping FAB (sekali ketuk);
- tutup: tombol ⌄ di kiri kotak ketik, tarik header ke bawah, ketuk latar
  redup di atas sheet, atau tombol/gestur Back Android (membuka chat menambah
  satu entri riwayat; menutup lewat tombol mengambilnya kembali).

Desktop: panel samping di bawah header, ditutup dengan X.

## Alur

```
ChatPanel.jsx ──POST /bot/chat/message {text, client_id}──▶ web_adapter.run_message
              ──POST /bot/chat/action  {message_id, data}──▶ web_adapter.run_action
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
- Perintah akun khusus Telegram (`/link`, `/unlink`, `/webapp`, tombol
  `merge_`/`unlink_`) tidak dijalankan di web; `/start` mengabaikan deep link.
- Teks yang berbeda per kanal memakai `is_web()` (mis. `/help`, ajakan setup,
  petunjuk `/template` & `/amplop_baru`).

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
