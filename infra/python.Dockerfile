FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.12.16-slim-bookworm AS base
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
COPY packages/python-common ./packages/python-common
RUN --mount=type=cache,id=radar-uv,target=/root/.cache/uv,sharing=locked uv sync --frozen --no-dev

FROM base AS runtime
COPY services ./services
COPY scripts ./scripts
USER 10001:10001
CMD [".venv/bin/uvicorn", "services.catalog.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS checks
RUN --mount=type=cache,id=radar-uv,target=/root/.cache/uv,sharing=locked uv sync --frozen
COPY services ./services
COPY scripts ./scripts
COPY tests/fixtures ./tests/fixtures
USER 10001:10001

