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

# Persistent data dir. On Railway, attach a Volume at /data via the
# project canvas so app.db (trades + alert config + auto-trade state)
# survives redeploys. Railway rejects the `VOLUME` Docker instruction
# (it manages mounts itself), so we only create the directory here for
# fallback boot when no volume is attached.
RUN mkdir -p /data

EXPOSE 8000
# Railway / generic platform: PORT env var; default to 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
