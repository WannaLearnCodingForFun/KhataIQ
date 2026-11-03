# One image for the API, the Celery worker, beat and migrations; the command picks the role.
FROM python:3.13-slim AS build
WORKDIR /src
COPY pyproject.toml ./
COPY khataiq ./khataiq
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    KHATAIQ_LABEL_MODEL_DIR=/app/models/label/v1
RUN useradd --create-home --uid 10001 khataiq
COPY --from=build /install /usr/local
WORKDIR /app
COPY alembic.ini ./
COPY alembic ./alembic
COPY models ./models
COPY scripts ./scripts
USER khataiq
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1
CMD ["uvicorn", "khataiq.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
