# Gong-NG demo/test image — the appliance with dummy audio (no ALSA).
# Build from the REPO ROOT so the legacy media is in context:
#   docker build -f ng/docker/Dockerfile -t gong-ng .
FROM python:3.11-slim-bookworm

RUN pip install --no-cache-dir flask waitress tzdata

COPY ng/ /opt/gong-ng/
COPY app/dhamma/gong-ting.mp3 app/dhamma/gong-drum.mp3 /opt/gong-ng/media-src/
COPY app/dhamma/doha/ /opt/gong-ng/media-src/doha/

RUN pip install --no-cache-dir --no-deps /opt/gong-ng \
    && mkdir -p /etc/gong-ng /var/lib/gong \
    && cp /opt/gong-ng/docker/config.toml /etc/gong-ng/config.toml \
    && chmod +x /opt/gong-ng/docker/entrypoint.sh

ENV GONG_CONFIG=/etc/gong-ng/config.toml
EXPOSE 80
VOLUME /var/lib/gong
CMD ["/opt/gong-ng/docker/entrypoint.sh"]
