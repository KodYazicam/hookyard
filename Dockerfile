FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY hookyard ./hookyard
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 hookyard
EXPOSE 4242
VOLUME ["/data"]
ENV HOOKYARD_DATA_FILE=/data/hookyard.json
USER 10001
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4242/health')"
CMD ["hookyard", "--host", "0.0.0.0", "--port", "4242", "--data-file", "/data/hookyard.json"]
