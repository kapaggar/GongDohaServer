# Gong-NG demo (Docker Hub)

PIN-protected mobile admin UI for the next-gen Gongserver, packaged as a
single container with **dummy audio** (no real speaker / ALSA).

| | |
|---|---|
| **Image** | `kapilgit/gong-ng:latest` |
| **Hub** | https://hub.docker.com/r/kapilgit/gong-ng |
| **Source branch** | [`gong-ng`](https://github.com/kapaggar/GongDohaServer/tree/gong-ng) |
| **Dockerfile** | [`ng/docker/Dockerfile`](../ng/docker/Dockerfile) |
| **Architecture** | `linux/arm64` only (Apple Silicon / Raspberry Pi) |
| **Size** | ~1.23 GB image (~540 MB compressed layers) |

On Intel/AMD hosts, Docker Desktop can run the image via arm64 emulation
(slower). A multi-arch rebuild is not published yet.

---

## Requirements

- Docker Desktop or Docker Engine
- ~1.5 GB free disk for the image

---

## Quick start

```bash
# Pull
docker pull kapilgit/gong-ng:latest

# Run demo (host 8090 → container 80)
docker run -d \
  --name gong-ng-demo \
  -p 8090:80 \
  -e GONG_PIN=4321 \
  -e GONG_DEMO=1 \
  -v gong-ng-data:/var/lib/gong \
  kapilgit/gong-ng:latest
```

Open the UI:

- http://127.0.0.1:8090/

**Demo PIN:** `4321`

---

## What you should see

- Dashboard (course day, toggles, next events, test buttons)
- Courses / schedule / sounds / time / play history
- Dummy audio: gong “plays” are timed only (no sound)

On first start the entrypoint (`ng/docker/entrypoint.sh`):

1. Initializes the SQLite DB under `/var/lib/gong`
2. Sets the PIN from `GONG_PIN` (default `4321`)
3. Seeds a demo course when `GONG_DEMO=1` (default)

---

## Useful commands

```bash
# Logs
docker logs -f gong-ng-demo

# Stop / start
docker stop gong-ng-demo
docker start gong-ng-demo

# Reset (wipes demo DB volume)
docker rm -f gong-ng-demo
docker volume rm gong-ng-data
# then re-run the docker run command above
```

---

## Optional: force platform (Intel Mac / x86 Linux)

```bash
docker run -d \
  --name gong-ng-demo \
  --platform linux/arm64 \
  -p 8090:80 \
  -e GONG_PIN=4321 \
  -e GONG_DEMO=1 \
  -v gong-ng-data:/var/lib/gong \
  kapilgit/gong-ng:latest
```

---

## Tags

| Tag | Meaning |
|-----|---------|
| `latest` | Current published demo image |
| `demo-2026-07-20` | Frozen tag matching the 2026-07-20 build |

Both tags currently point at the same image digest.

---

## Publishing (maintainers)

Requires Docker Hub login as `kapilgit` (or update the image name).

```bash
# From repo root on gong-ng, after a local build:
#   docker build -f ng/docker/Dockerfile -t gong-ng .

docker tag gong-ng:latest kapilgit/gong-ng:latest
docker tag gong-ng:latest kapilgit/gong-ng:demo-YYYY-MM-DD
docker push kapilgit/gong-ng:latest
docker push kapilgit/gong-ng:demo-YYYY-MM-DD
```

Optional multi-arch (amd64 + arm64) with buildx:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -f ng/docker/Dockerfile -t kapilgit/gong-ng:latest --push .
```

---

## Notes / limits

- Software **UI + scheduler demo**, not a full Pi appliance (no hostapd AP,
  GPIO relay, or real audio hardware).
- Image is **arm64-only** today; use `--platform linux/arm64` or wait for a
  multi-arch publish.
- Change `GONG_PIN` for your own tests; do not reuse a production PIN.
- Gong/doha media rights: follow the repo [LICENSE](../LICENSE) NOTICE for
  redistribution of audio.

---

## Related docs

- [ng/README.md](../ng/README.md) — Gong-NG overview and local (non-Docker) dev
- [TESTING-ON-MAC.md](TESTING-ON-MAC.md) — legacy LAMP docker-compose stack
- [GONG-NG-DESIGN.md](GONG-NG-DESIGN.md) — design document
