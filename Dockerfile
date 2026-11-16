# Image AWS Lambda (Python 3.12) untuk pre-screening video review.
# Whisper sengaja tidak dipasang: transkrip memakai Gemini (ASR_MODEL).
FROM public.ecr.aws/lambda/python:3.12

# ffmpeg statis (tidak tersedia di repo paket Amazon Linux)
COPY --from=mwader/static-ffmpeg:7.0.2 /ffmpeg /usr/local/bin/ffmpeg

COPY requirements-lambda.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements-lambda.txt

COPY core/ ${LAMBDA_TASK_ROOT}/core/
COPY handler.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.handler"]
