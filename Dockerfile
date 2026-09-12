FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY hookyard ./hookyard
RUN pip install --no-cache-dir .
EXPOSE 4242
VOLUME ["/data"]
ENV HOOKYARD_DATA_FILE=/data/hookyard.json
CMD ["hookyard", "--host", "0.0.0.0", "--port", "4242", "--data-file", "/data/hookyard.json"]
