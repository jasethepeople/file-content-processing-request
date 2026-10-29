FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

RUN addgroup --system hermes && adduser --system --ingroup hermes --home /app hermes \
    && apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY config/config.example.yaml ./config/config.example.yaml

RUN mkdir -p /var/lib/hermes /opt/hermes/plugins \
    && chown -R hermes:hermes /app /var/lib/hermes /opt/hermes/plugins

USER hermes
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
