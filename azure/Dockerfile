FROM node:22-alpine AS frontend
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FARMCRAFT_STATIC_DIR=/app/frontend/dist
COPY requirements-api.txt requirements-azure.txt ./
RUN pip install --no-cache-dir -r requirements-azure.txt
COPY . .
COPY --from=frontend /ui/dist /app/frontend/dist
RUN useradd --system --uid 10001 farmcraft && chown -R farmcraft:farmcraft /app
USER 10001
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
