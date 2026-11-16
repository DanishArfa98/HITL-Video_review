# Dashboard Review Video (React)

Vite + React + TypeScript. Berbicara dengan API di AWS Lambda (lihat PANDUAN-API.md).

## Menjalankan di laptop
Di folder `frontend` (butuh Node.js 20 ke atas):
```
npm install
npm run dev
```
Buka alamat yang tampil (biasanya http://localhost:5173). Di layar login isi **alamat API**
(Function URL Lambda) dan **token** (nilai `API_TOKEN` di Lambda).
Alamat API bisa juga ditetapkan lewat file `.env` (salin dari `.env.example`).

## Tes logika
```
npm test
```

## Build untuk produksi
```
npm run build
```
Hasilnya di folder `dist/`. Lihat PANDUAN-FRONTEND.md untuk deploy ke Cloudflare Pages.

## Mencoba tampilan tanpa AWS
`npm run mock` menjalankan API tiruan di http://localhost:8787 (token: `demo`).
Isi alamat API dengan `http://localhost:8787` di layar login.
