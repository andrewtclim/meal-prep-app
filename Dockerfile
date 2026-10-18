# could switch to python:3.11-slim once dependencies are settled, to shrink the image (maybe)
FROM python:3.12

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv

WORKDIR /code

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

ENV PATH="/code/.venv/bin:$PATH"

COPY app/ app/

# 0.0.0.0 so the server is reachable from outside the container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
