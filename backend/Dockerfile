FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

ARG INSTALL_DEV=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml ./
RUN if [ "$INSTALL_DEV" = "true" ]; then uv sync --no-install-project; \
    else uv sync --no-install-project --no-dev; fi

COPY . .

# Installed outside /app, so the compose bind mount of ./backend cannot shadow
# it, with any CRLF line endings stripped: a Windows checkout without
# .gitattributes would otherwise fail with "exec /app/entrypoint.sh: no such file".
RUN sed 's/\r$//' entrypoint.sh > /usr/local/bin/entrypoint.sh \
    && chmod 755 /usr/local/bin/entrypoint.sh

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
