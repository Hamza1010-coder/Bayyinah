FROM python:3.12-slim

WORKDIR /app

# Only two optional dependencies: Word export and PDF ingest.
# The application core is stdlib-only.
RUN pip install --no-cache-dir python-docx==1.2.0 pypdf==5.1.0

COPY bayyinah/ ./bayyinah/
COPY evals/ ./evals/
COPY scripts/ ./scripts/
COPY corpora/ ./corpora/

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    BAYYYINAH_DB_PATH=/data/bayyinah.db

RUN mkdir -p /data && \
    python -m bayyinah ingest corpora/raw

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health')"

CMD ["python", "-m", "bayyinah", "serve", "--host", "0.0.0.0", "--port", "8080"]
