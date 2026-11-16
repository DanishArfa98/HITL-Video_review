# Panduan AWS: S3 -> SQS -> Lambda -> DynamoDB

Region yang dipakai di panduan ini: **ap-southeast-1 (Singapura)**. Pakai region yang sama
untuk semua layanan. Perintah dijalankan di PowerShell, satu per satu.

## 0. Keamanan dan biaya (kerjakan dulu)
1. Aktifkan MFA di akun root, lalu buat **IAM user** untuk pekerjaan sehari-hari
   (jangan pakai root). Beri izin AdministratorAccess untuk side-project ini, buat access key.
2. Buka **Billing > Budgets**, buat budget bulanan **1 USD** dengan notifikasi email.
3. Pasang AWS CLI: `winget install -e --id Amazon.AWSCLI`, buka terminal baru, lalu
   `aws configure` (isi access key, secret, region `ap-southeast-1`, output `json`).
   Cek: `aws sts get-caller-identity`.

Catatan biaya: Lambda, DynamoDB (kapasitas provisioned), dan SQS punya jatah gratis tetap
tiap bulan. Penyimpanan S3 dan ECR ditanggung kredit akun baru, lalu berbayar sangat kecil
(centang di Billing). Perkiraan kasar: 1 video sekitar 60 detik x 2 GB = 120 GB-detik, jadi
300 video per minggu masih jauh di bawah jatah Lambda (400.000 GB-detik per bulan).

## 1. Dua tabel DynamoDB
Pakai kapasitas **provisioned** (jatah gratis hanya untuk mode ini; mode on-demand tidak gratis).
```
aws dynamodb create-table --table-name video-review-templates --attribute-definitions AttributeName=template_id,AttributeType=S --key-schema AttributeName=template_id,KeyType=HASH --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5
```
```
aws dynamodb create-table --table-name video-review-results --attribute-definitions AttributeName=video_id,AttributeType=S --key-schema AttributeName=video_id,KeyType=HASH --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5
```

## 2. Bucket S3 untuk video
Nama bucket harus unik sedunia. Ganti `NAMA-ANDA`:
```
aws s3api create-bucket --bucket video-review-NAMA-ANDA --region ap-southeast-1 --create-bucket-configuration LocationConstraint=ap-southeast-1
```
Di konsol S3 > bucket > **Management > Lifecycle rules**, buat aturan hapus objek
berawalan `uploads/` setelah 7 hari, supaya penyimpanan tidak menumpuk.

## 3. Build ulang image dan dorong ke ECR
Di folder proyek (Docker Desktop harus menyala):
```
docker build --provenance=false -t video-review .
```
(`--provenance=false` mencegah Lambda menolak image dengan error "media type not supported".)
```
$acct = aws sts get-caller-identity --query Account --output text
```
```
aws ecr create-repository --repository-name video-review --region ap-southeast-1
```
```
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin "$acct.dkr.ecr.ap-southeast-1.amazonaws.com"
```
```
docker tag video-review:latest "$acct.dkr.ecr.ap-southeast-1.amazonaws.com/video-review:latest"
```
```
docker push "$acct.dkr.ecr.ap-southeast-1.amazonaws.com/video-review:latest"
```
Jika laptop Anda berarsitektur ARM (bukan Intel/AMD), pilih arsitektur arm64 saat membuat Lambda.

## 4. Role IAM untuk Lambda (konsol IAM)
1. IAM > Roles > Create role > AWS service > **Lambda**.
2. Lampirkan kebijakan `AWSLambdaBasicExecutionRole` (untuk log) dan `AWSLambdaSQSQueueExecutionRole`.
3. Beri nama `video-review-lambda-role`, lalu buka role itu > Add permissions > Create inline
   policy > JSON (ganti NAMA-ANDA dan ACCOUNT-ID):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": ["s3:GetObject"],
     "Resource": "arn:aws:s3:::video-review-NAMA-ANDA/*"},
    {"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem"],
     "Resource": [
       "arn:aws:dynamodb:ap-southeast-1:ACCOUNT-ID:table/video-review-templates",
       "arn:aws:dynamodb:ap-southeast-1:ACCOUNT-ID:table/video-review-results"]}
  ]
}
```
(Handler membaca metadata objek lewat `head_object`, yang dicakup izin `s3:GetObject`.)

## 5. Fungsi Lambda (konsol Lambda)
1. Create function > **Container image** > nama `video-review` > Browse images > pilih
   repo `video-review` tag `latest` > Existing role `video-review-lambda-role`.
2. Configuration > General configuration: **Memory 2048 MB, Timeout 15 menit, Ephemeral storage 2048 MB**.
3. Configuration > Environment variables:
   - `GEMINI_API_KEY` = key Anda (cukup untuk side-project; produksi sebaiknya SSM/Secrets Manager)
   - `TEMPLATES_TABLE` = `video-review-templates`
   - `RESULTS_TABLE` = `video-review-results`

## 6. Antrean SQS (+ dead-letter queue)
1. SQS > Create queue > Standard > `video-review-dlq` (antrean untuk pesan yang gagal terus).
2. Create queue > Standard > `video-review-jobs`:
   - Visibility timeout: **5400 detik** (6 kali timeout Lambda; syarat dari AWS minimal sama dengan timeout)
   - Dead-letter queue: aktifkan, pilih `video-review-dlq`, Maximum receives = 2
   - Access policy (ganti ACCOUNT-ID dan NAMA-ANDA), supaya S3 boleh mengirim pesan:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "s3.amazonaws.com"},
    "Action": "sqs:SendMessage",
    "Resource": "arn:aws:sqs:ap-southeast-1:ACCOUNT-ID:video-review-jobs",
    "Condition": {"ArnLike": {"aws:SourceArn": "arn:aws:s3:::video-review-NAMA-ANDA"}}
  }]
}
```

## 7. Hubungkan S3 ke SQS ke Lambda
1. S3 > bucket > Properties > **Event notifications** > Create:
   Prefix `uploads/`, Suffix `.mp4`, event "All object create events", tujuan SQS `video-review-jobs`.
2. Lambda > fungsi `video-review` > **Add trigger** > SQS > `video-review-jobs`:
   Batch size **1**, centang **Report batch item failures**, Maximum concurrency **2**
   (membatasi panggilan paralel ke Gemini agar tidak kena batas kuota).

## 8. Uji
1. S3 > bucket > **Upload** file `contoh.mp4` ke folder `uploads/`. Buka "Properties" pada
   formulir unggah > **Metadata** > Add metadata: tipe *User defined*, kunci `role` nilai `satpam`,
   kunci `title` nilai judul skenario (huruf latin biasa, tanpa karakter khusus).
2. Tunggu 1 sampai 3 menit. Pantau di Lambda > Monitor > View CloudWatch logs.
3. Hasil: DynamoDB > Tables > `video-review-results` > Explore items. Item bernama
   `vid_<nama-file>` berisi seluruh hasil (results, timeline, summary).

## Jika gagal
- Pesan masuk ke `video-review-dlq`: lihat log CloudWatch, kirim baris error ke saya.
- Tidak ada log sama sekali: periksa trigger SQS aktif dan event notification S3 benar.
- Error izin (AccessDenied): periksa nama bucket dan ACCOUNT-ID di kebijakan IAM.

## Merapikan setelah selesai (hindari biaya)
Hapus fungsi Lambda, antrean SQS, bucket (kosongkan dulu), repository ECR, dan tabel DynamoDB
jika tidak dipakai lagi.
