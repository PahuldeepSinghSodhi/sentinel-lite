FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false HF_HOME=/opt/models HOME=/tmp \
    SENTINEL_EMBEDDING_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41
WORKDIR /app
COPY aws/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes --extra-index-url https://download.pytorch.org/whl/cpu -r /tmp/requirements.lock
RUN python -c "import os; from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2', revision=os.environ['SENTINEL_EMBEDDING_REVISION'])"
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 SENTINEL_MODE=cloud SENTINEL_CLOUD_PROVIDER=aws
COPY app /app/app
COPY aws /app/aws
COPY data/sample_transactions.csv data/rate_card.csv /app/data/
COPY data/sample_docs/service_agreement.txt /app/data/sample_docs/
RUN groupadd --gid 10001 sentinel && useradd --uid 10001 --gid 10001 --no-create-home sentinel \
    && mkdir -p /app/index_data && chown 10001:10001 /app/index_data
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1","--no-access-log"]
