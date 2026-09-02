# syntax=docker/dockerfile:1.7
FROM python:3.13-slim-bookworm

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/var/lib/micromatrix

RUN groupadd --gid "${APP_GID}" micromatrix \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" \
        --home-dir /var/lib/micromatrix --create-home \
        --shell /usr/sbin/nologin micromatrix

WORKDIR /opt/micromatrix-workbench

COPY requirements-server.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-server.txt

COPY agent_runtime ./agent_runtime
COPY agent_workbench ./agent_workbench
COPY start.py LICENSE ./

RUN mkdir -p /run/micromatrix /workspace /var/lib/micromatrix \
    && chown -R micromatrix:micromatrix \
        /run/micromatrix /workspace /var/lib/micromatrix

USER micromatrix:micromatrix

EXPOSE 8234
VOLUME ["/workspace", "/var/lib/micromatrix"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8234/.well-known/micromatrix-workbench-health', timeout=3); raise SystemExit(0 if response.status == 200 else 1)"]

ENTRYPOINT ["python", "/opt/micromatrix-workbench/start.py"]
CMD ["/workspace", "--host", "0.0.0.0", "--port", "8234", "--env-file", "/run/micromatrix/server.env"]
