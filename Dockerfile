FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

RUN groupadd --system --gid 10001 signboard \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --no-create-home signboard

COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY app ./app
COPY static ./static
RUN mkdir -p /app/data/signatures \
    && chown -R signboard:signboard /app

USER signboard

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
