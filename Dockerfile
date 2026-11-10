FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY durst ./durst
RUN uv sync --frozen --no-dev
ENV PATH=/app/.venv/bin:$PATH DURST_DB=/data/durst.db
VOLUME /data
EXPOSE 2222
CMD ["durst", "serve", "--host-key", "/data/ssh_host_key"]
