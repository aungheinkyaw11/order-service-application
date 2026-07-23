FROM python:3.12.11-slim-bookworm AS base

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip==25.1.1 \
    && pip install --requirement requirements.txt



FROM base AS development

COPY requirements-dev.txt .
RUN pip install --requirement requirements-dev.txt



FROM base AS runtime

ARG IMAGE_VERSION=local
ENV IMAGE_VERSION=${IMAGE_VERSION}

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app app

COPY --chown=app:app app ./app
COPY --chown=app:app migrations ./migrations

USER app
EXPOSE 8000
CMD ["python", "-m", "app.api_entrypoint"]