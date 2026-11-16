# Panduan Frontend (Dashboard Review)

Semua perintah dijalankan di PowerShell, di dalam folder `frontend`.

## 1. Coba dulu tanpa AWS (API tiruan)
Syarat: Node.js 20+ (https://nodejs.org, pilih LTS).

```powershell
npm install
npm run mock      # jendela 1: API tiruan di http://localhost:8787
npm run dev       # jendela 2: dashboard di http://localhost:5173
```
Login: URL API `http://localhost:8787`, token `demo`.
Video contoh tiruan memakai `mock/sample.mp4` (opsional; buat sendiri dengan video pendek apa saja diberi nama itu). Tanpa file itu, daftar dan checklist tetap bisa dicoba.

## 2. Pakai API sungguhan
Jalankan `npm run dev`, buka http://localhost:5173, login dengan:
- URL API = Function URL Lambda API (lihat PANDUAN-API.md)
- Token = nilai `API_TOKEN` yang kamu isi sendiri di Lambda API

Token disimpan di browser (localStorage) saja. Jangan ditempel ke chat/repo.

Pada pemakaian pertama browser bisa menolak unggahan/video karena CORS. Lihat langkah 4.

## 3. Deploy gratis ke Cloudflare Pages
Cara termudah (tanpa Git): 
```powershell
npm run build
```
Lalu di dash.cloudflare.com, Workers & Pages, Create, Pages, **Upload assets**, seret folder `dist`. Dapat alamat `https://nama-proyek.pages.dev`.

Cara lewat GitHub: build command `npm run build`, output directory `dist`, root directory `frontend`.

Alamat API dimasukkan lewat layar login, jadi tidak wajib mengatur `VITE_API_URL`. Jika ingin terisi otomatis, buat file `.env` berisi `VITE_API_URL=https://xxxx.lambda-url.ap-southeast-1.on.aws` sebelum `npm run build`.

## 4. Persempit CORS (setelah alamat dashboard tetap)
1. Lambda API, Configuration, Environment variables: `ALLOWED_ORIGINS` = `https://nama-proyek.pages.dev` (tanpa garis miring di akhir; pisah koma jika lebih dari satu, mis. tambahkan `http://localhost:5173` selama pengembangan). Simpan.
2. S3 bucket video, Permissions, CORS: ubah `AllowedOrigins` dari `*` ke alamat yang sama. Methods tetap `PUT` dan `GET`, `AllowedHeaders` `*`.

## 5. Keterbatasan saat ini
- Bukti gambar hanya tampil sebagai detik (klik untuk lompat); frame belum disimpan di S3.
- Hasil lama tanpa `source` tidak bisa memutar video (proses ulang videonya).
- Tipe TypeScript belum diperiksa mesin; jalankan `npm run typecheck` dan kabari jika ada error.
- Perbaikan kualitas AI (cek kesesuaian judul, voting 3 run) belum dikerjakan.

## Pintasan di halaman review
K putar/jeda, J mundur 5 dtk, L maju 5 dtk.
