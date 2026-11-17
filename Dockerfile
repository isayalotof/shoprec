FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SHOPREC_HOST=0.0.0.0 \
    SHOPREC_PORT=8787 \
    SHOPREC_DATA_DIR=/app/data

RUN groupadd --gid 10001 shoprec && useradd --uid 10001 --gid 10001 --no-create-home shoprec
WORKDIR /app
COPY --chown=10001:10001 server.py storage.py recommender.py seed.py ./
COPY --chown=10001:10001 static ./static
RUN mkdir /app/data && chown 10001:10001 /app/data
USER 10001:10001
EXPOSE 8787
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=2).read()" || exit 1
CMD ["python", "server.py"]
