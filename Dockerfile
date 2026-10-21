#Сборка зависимостей, установка утилит

FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
	build-essential \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --user -r requirements.txt


FROM python:3.11-slim AS runner

WORKDIR /app

RUN useradd -u 8888 appuser && chown -R appuser:appuser /app
USER appuser

COPY --from=builder /root/.local /home/appuser/.local
COPY --chown=appuser:appuser app.py .

ENV PATH=/home/appuser/.local/bin:$PATH

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
