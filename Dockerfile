FROM python:3.12-slim-bookworm

# Docker標準のproxy build argsを使う。ARG/ENVへの再宣言はせず、イメージに残さない。
# ComposeからHTTP_PROXY等を渡し、apt・pip・Playwrightの取得に使う。
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Tokyo \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY requirements.txt ./
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates fonts-noto-cjk tzdata \
    && pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 mcp \
    && mkdir -p /data/repos /data/artifacts /data/browser \
    && chown -R mcp:mcp /data
COPY app ./app
COPY scripts ./scripts
COPY config/config.example.toml ./config/config.example.toml
RUN chmod +x /app/app/git_askpass.py
USER mcp
EXPOSE 8000
CMD ["python", "-m", "app.server"]
