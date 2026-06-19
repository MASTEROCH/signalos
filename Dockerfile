FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# данные (SQLite + TG-сессии) — в /data; примонтируй диск для постоянного хранения
ENV SIGNALOS_DB=/data/signalos.db
RUN mkdir -p /data
EXPOSE 8000
CMD ["python", "-m", "signalos.server"]
