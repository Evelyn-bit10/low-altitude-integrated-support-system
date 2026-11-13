# 构建上下文为项目根目录(low-altitude-demo)
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY frontend /app/frontend

ENV PYTHONUNBUFFERED=1 \
    FRONTEND_DIR=/app/frontend
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
