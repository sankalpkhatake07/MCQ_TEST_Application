FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# DejaVu gives the PDF reports a Unicode-capable font
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-optional.txt ./
ARG WITH_OPTIONAL=false
RUN pip install --no-cache-dir -r requirements.txt && if [ "$WITH_OPTIONAL" = "true" ]; then pip install --no-cache-dir -r requirements-optional.txt; fi
COPY . .
RUN useradd -m app && mkdir -p /data && chown -R app /app /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:8000/api/health || exit 1
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers ${UVICORN_WORKERS:-1}"]
