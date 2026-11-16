# Panduan Docker dan uji Lambda lokal (Windows, PowerShell)

Semua perintah dijalankan di folder proyek (`video-review`), satu perintah per baris.

## 1. Pasang Docker Desktop
1. Pastikan virtualisasi aktif (Task Manager > Performance > CPU > "Virtualization: Enabled").
   Jika "Disabled", aktifkan lewat BIOS (opsi Intel VT-x / AMD SVM).
2. Pasang:
   `winget install -e --id Docker.DockerDesktop`
3. Restart laptop bila diminta (installer memasang WSL2 otomatis).
4. Buka aplikasi **Docker Desktop**, setujui lisensi (gratis untuk pribadi/pendidikan),
   tunggu sampai ikon paus di pojok bawah berstatus "Engine running".
5. Buka terminal PowerShell BARU, lalu cek:
   `docker version`
   `docker run --rm hello-world`
   Jika muncul "Hello from Docker!", Docker siap.

## 2. Siapkan folder uji
```
mkdir data
mkdir out
copy contoh.mp4 data\contoh.mp4
```
(`data\` dan `out\` tidak ikut masuk image dan tidak ikut git.)

## 3. Build image (pertama kali 3 sampai 10 menit)
```
docker build -t video-review .
```
Jika gagal, kirim 20 baris terakhir pesan error-nya.

## 4. Jalankan Lambda lokal (terminal pertama, biarkan terbuka)
Aktifkan dulu API key di terminal ini:
```
$env:GEMINI_API_KEY="isi-api-key-baru"
```
Lalu:
```
docker run --rm -p 9000:8080 -e GEMINI_API_KEY=$env:GEMINI_API_KEY -v ${PWD}\data:/data -v ${PWD}\out:/tmp/results -v ${PWD}\templates:/tmp/templates video-review
```
Arti singkatnya: `-p 9000:8080` membuka Lambda di alamat localhost:9000;
tiga `-v` menghubungkan folder laptop (video, hasil, template) ke dalam container.

## 5. Panggil fungsi (terminal kedua)
```
Invoke-RestMethod -Method Post -Uri "http://localhost:9000/2015-03-31/functions/function/invocations" -Body (Get-Content events\uji-lokal.json -Raw)
```
Tunggu 1 sampai 3 menit (Gemini bekerja). Balasannya berisi `video_id`, jumlah pass/fail,
`needs_attention`. File lengkapnya muncul di `out\vid_contoh.json`.

Hasil yang diharapkan untuk `contoh.mp4`: U-06 pass, `needs_attention` false.
Ganti `local_video` dan `title` di `events\uji-lokal.json` untuk video lain
(mis. `/data/ditolak1.mp4`, harapannya U-06 fail).

## 6. Berhenti
Tekan Ctrl+C di terminal pertama.

## Setelah ini (belum dikerjakan)
- S3 (unggah video) -> SQS -> Lambda -> DynamoDB (hasil dan template)
- Push image ke ECR, buat fungsi Lambda dari image (timeout 15 menit, /tmp dibesarkan)
- FastAPI, lalu dashboard React
