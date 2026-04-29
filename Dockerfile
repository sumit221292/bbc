# --- Stage 1: build the React frontend ---
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python backend, with the built frontend bundled in ---
FROM python:3.11-slim
WORKDIR /app

# Backend deps
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Backend source
COPY backend/ ./

# Static frontend bundle (served by FastAPI in production)
COPY --from=frontend-build /app/frontend/dist ./frontend_dist

EXPOSE 8000
# Railway / generic platform: PORT env var; default to 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
