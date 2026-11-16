# Panduan: API (FastAPI) di Lambda

Melanjutkan PANDUAN-AWS.md. Region yang sama (ap-southeast-1). Perintah di PowerShell,
dijalankan di folder proyek kecuali disebut lain.

## Endpoint
| Metode dan alamat | Fungsi |
|---|---|
| `GET /health` | Cek hidup (tanpa token) |
| `POST /uploads` | Minta tautan unggah S3 sementara. Body: `{"filename","role","title"}` |
| `GET /videos` | Daftar video, terbaru di atas |
| `GET /videos/{video_id}` | Hasil AI, keputusan reviewer, template, tautan putar video |
| `PUT /videos/{video_id}/review` | Simpan override dan Approve/Reject (+ edit checklist) |
| `GET /templates/{role}/{scenario_id}` | Ambil template |

Semua kecuali `/health` butuh header `Authorization: Bearer <API_TOKEN>`.

## 1. Tabel DynamoDB untuk keputusan reviewer
Keputusan manusia disimpan terpisah dari hasil AI, supaya memproses ulang video tidak menimpanya.
```
aws dynamodb create-table --table-name video-review-reviews --attribute-definitions AttributeName=video_id,AttributeType=S --key-schema AttributeName=video_id,KeyType=HASH --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5
```
(Total kapasitas tiga tabel: 15 RCU dan 15 WCU, masih di bawah jatah gratis 25.)

## 2. Perbarui Lambda pipeline (agar menyimpan lokasi video)
Handler v11 menyimpan lokasi video di hasil, dipakai untuk tautan putar.
Build, push, lalu **Deploy new image** (langkah 3 di PANDUAN-AWS.md). Hasil lama tidak punya
lokasi video, jadi unggah ulang video uji. Sekalian turunkan memori Lambda pipeline ke
**1024 MB** (pemakaian nyata hanya sekitar 245 MB).

## 3. CORS bucket S3 (agar browser boleh mengunggah)
Buat file `cors.json`:
```json
{"CORSRules": [{
  "AllowedOrigins": ["*"],
  "AllowedMethods": ["PUT", "GET"],
  "AllowedHeaders": ["*"],
  "ExposeHeaders": ["ETag"],
  "MaxAgeSeconds": 3000
}]}
```
```
aws s3api put-bucket-cors --bucket video-review-NAMA-ANDA --cors-configuration file://cors.json
```
Setelah dashboard punya alamat tetap, ganti `*` dengan alamat itu.

## 4. Image API ke ECR
```
docker build --provenance=false -f Dockerfile.api -t video-review-api .
```
```
$acct = aws sts get-caller-identity --query Account --output text
```
```
aws ecr create-repository --repository-name video-review-api --region ap-southeast-1
```
```
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin "$acct.dkr.ecr.ap-southeast-1.amazonaws.com"
```
```
docker tag video-review-api:latest "$acct.dkr.ecr.ap-southeast-1.amazonaws.com/video-review-api:latest"
```
```
docker push "$acct.dkr.ecr.ap-southeast-1.amazonaws.com/video-review-api:latest"
```

## 5. Role IAM untuk API
IAM > Roles > Create role > Lambda > lampirkan `AWSLambdaBasicExecutionRole` > nama
`video-review-api-role` > inline policy (ganti NAMA-ANDA dan ACCOUNT-ID):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Scan"],
     "Resource": [
       "arn:aws:dynamodb:ap-southeast-1:ACCOUNT-ID:table/video-review-templates",
       "arn:aws:dynamodb:ap-southeast-1:ACCOUNT-ID:table/video-review-results",
       "arn:aws:dynamodb:ap-southeast-1:ACCOUNT-ID:table/video-review-reviews"]},
    {"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject"],
     "Resource": "arn:aws:s3:::video-review-NAMA-ANDA/*"}
  ]
}
```

## 6. Fungsi Lambda API
1. Lambda > Create function > **Container image** > nama `video-review-api` > image
   `video-review-api:latest` > role `video-review-api-role`.
2. Configuration > General: **Memory 512 MB, Timeout 30 detik**.
3. Environment variables:
   - `RESULTS_TABLE` = `video-review-results`
   - `REVIEWS_TABLE` = `video-review-reviews`
   - `TEMPLATES_TABLE` = `video-review-templates`
   - `VIDEO_BUCKET` = `video-review-NAMA-ANDA`
   - `ALLOWED_ORIGINS` = `*`
   - `API_TOKEN` = string acak panjang. Buat di PowerShell:
     `[guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")`
     Simpan; dashboard akan meminta token ini saat login. Jangan dibagikan.

## 7. Alamat publik (Function URL)
Configuration > **Function URL** > Create: Auth type **NONE** (keamanan dipegang token
aplikasi). **Jangan** isi bagian CORS di sini, CORS sudah ditangani FastAPI. Salin URL-nya.

## 8. Uji
```
Invoke-RestMethod "https://URL-ANDA.lambda-url.ap-southeast-1.on.aws/health"
```
```
Invoke-RestMethod "https://URL-ANDA.lambda-url.ap-southeast-1.on.aws/videos" -Headers @{Authorization="Bearer TOKEN-ANDA"}
```
Yang pertama harus menjawab `ok: True`. Yang kedua menampilkan daftar video (kosong jika belum ada).
Tanpa token harus ditolak (401).

## Jika gagal
- 403 Forbidden dari URL itu sendiri: periksa Configuration > Permissions > Resource-based policy
  fungsi, harus ada izin untuk Function URL (konsol biasanya menambahkannya otomatis).
- 500 "API_TOKEN belum diset": variabel lingkungan belum terisi.
- 500 lain: lihat CloudWatch log fungsi `video-review-api`, kirim baris error ke saya.

## Uji lokal tanpa Docker (opsional)
Di venv: `pip install fastapi uvicorn mangum httpx`, set variabel lingkungan yang sama
(`$env:RESULTS_TABLE="video-review-results"` dan seterusnya, termasuk `API_TOKEN`), lalu
`uvicorn api.main:app --reload`. Dokumentasi interaktif ada di http://localhost:8000/docs.
