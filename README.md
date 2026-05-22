# MixStream

MixStream is a self-hosted web app for uploading, sharing, and listening to DJ mixes.

It is built for people who want a small private or public mix library they can run themselves with Docker. Upload a mix, let the worker create web-friendly playback files, then share public mixes, private mixes, profile pages, and track IDs from your own server.

Repository: <https://github.com/oliver-louis/mixstream>

> Status: early self-hostable project. It is usable, but expect rough edges while the deployment and documentation mature.

## What It Does

- Upload long DJ mixes and cover art.
- Browse public mixes without logging in.
- Keep mixes private or share them with selected users.
- Add structured track IDs with timestamps and links.
- Generate Opus and MP3 playback files with `ffmpeg`.
- Generate resized WebP cover images.
- Serve audio through nginx after Django authorizes access.
- Sign in with authentik/OIDC for production deployments.
- Run with Docker Compose, Postgres, Django, nginx, and a media-processing worker.

## How It Works

MixStream runs as a small Docker Compose stack:

- `db`: Postgres database.
- `app`: Django + Gunicorn web app.
- `worker`: background media processor for audio, covers, duration, and waveform data.
- `nginx`: serves static files, public image derivatives, and protected audio streams.

Uploaded media lives outside the container in a host folder you choose with `NAS_MEDIA_PATH`.

## Quick Start

You need:

- Docker Engine
- Docker Compose plugin
- A folder where Docker can store uploaded media

Clone the repo:

```sh
git clone https://github.com/oliver-louis/mixstream.git
cd mixstream
```

Copy an environment template:

```sh
cp .env.example .env
```

Generate secrets:

```sh
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
openssl rand -base64 32
```

Edit `.env` and set at least:

```env
DJANGO_SECRET_KEY=<generated django secret>
POSTGRES_PASSWORD=<generated postgres password>
NAS_MEDIA_PATH=/path/on/your/host/mixstream-media
DJANGO_ALLOWED_HOSTS=your-hostname-or-ip
DJANGO_CSRF_TRUSTED_ORIGINS=https://your-hostname
```

Start the stack:

```sh
docker compose up -d --build
```

Check that it is healthy:

```sh
docker compose ps
docker compose logs -f app worker nginx
```

Open the app using the host and port configured in `.env`. By default:

```text
http://localhost:8088
```

## First LAN/VM Deployment

If you are just trying MixStream on a local Docker host, such as a Debian VM, start with the LAN/dev template:

```sh
cp .env.vm.example .env
nano .env
```

Set:

```env
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<VM-IP>
DJANGO_CSRF_TRUSTED_ORIGINS=http://<VM-IP>:8081
NAS_MEDIA_PATH=/opt/stacks/mixstream/media
APP_PORT=8081
OIDC_ENABLED=false
DJANGO_DEBUG=true
```

Then:

```sh
mkdir -p /opt/stacks/mixstream/media
docker compose up -d --build
docker compose exec app python manage.py createsuperuser
```

Open:

```text
http://<VM-IP>:8081
```

More detail is in [docs/deploy-debian-vm.md](docs/deploy-debian-vm.md).

## Production Setup

For a real self-hosted deployment, put MixStream behind a reverse proxy such as Nginx Proxy Manager, Caddy, Traefik, or nginx.

Recommended production basics:

- Set `DJANGO_DEBUG=false`.
- Use a long random `DJANGO_SECRET_KEY`.
- Use a long random `POSTGRES_PASSWORD`.
- Set `DJANGO_ALLOWED_HOSTS` to your public hostname.
- Set `DJANGO_CSRF_TRUSTED_ORIGINS` to your public `https://` origin.
- Set `SESSION_COOKIE_SECURE=true` and `CSRF_COOKIE_SECURE=true`.
- Keep Postgres internal to the Compose network.
- Back up both Postgres and the media folder.

The default production path expects authentik/OIDC:

```env
OIDC_ENABLED=true
OIDC_RP_CLIENT_ID=<authentik client id>
OIDC_RP_CLIENT_SECRET=<authentik client secret>
OIDC_OP_AUTHORIZATION_ENDPOINT=https://auth.example.com/application/o/authorize/
OIDC_OP_TOKEN_ENDPOINT=https://auth.example.com/application/o/token/
OIDC_OP_USER_ENDPOINT=https://auth.example.com/application/o/userinfo/
OIDC_OP_JWKS_ENDPOINT=https://auth.example.com/application/o/mixstream/jwks/
```

In authentik, add the callback URL:

```text
https://your-mixstream-host/oidc/callback/
```

Production mode intentionally refuses to start with placeholder secrets, wildcard hosts, missing CSRF origins, missing database config, insecure cookies, or missing OIDC settings.

## Updating

If you deployed from Git:

```sh
cd /opt/stacks/mixstream
git pull
docker compose up -d --build
docker compose ps
```

Watch logs after updating:

```sh
docker compose logs -f app worker nginx
```

## Useful Commands

Run Django management commands:

```sh
docker compose exec app python manage.py check
docker compose exec app python manage.py createsuperuser
docker compose exec app python manage.py migrate
docker compose exec app python manage.py collectstatic --noinput
```

Retry media processing:

```sh
docker compose exec worker python manage.py process_mix_media --failed --once
```

Reprocess all media derivatives:

```sh
docker compose exec worker python manage.py process_mix_media --all --once
```

Check resource use:

```sh
docker stats
docker system df
```

## Media Storage and Privacy

Original uploads and processed media are stored below `DJMIX_MEDIA_ROOT`, which maps to `/media` inside Docker.

In normal Docker deployments, set:

```env
NAS_MEDIA_PATH=/mnt/nas/mixstream-media
```

The app keeps original uploads for future reprocessing. The worker creates:

- Opus audio for normal playback.
- MP3 audio as a compatibility fallback.
- Large WebP cover art.
- 480px WebP thumbnails.

Audio files are protected. Django checks permissions first, then nginx serves the file internally through `X-Accel-Redirect`. Direct `/media/mixes/` access is denied by nginx.

Cover and profile images are intentionally served directly by nginx with long cache headers. Treat cover art, profile pictures, and banners as public if someone knows the URL, even when a mix itself is private.

## Backups

Back up the database and media folder together. Restoring only one side can leave broken mix records or orphaned files.

Back up:

- The Docker volume `mixstream_postgres-data`.
- The host folder configured as `NAS_MEDIA_PATH`.
- Your private `.env` file.

Restore by stopping the stack, restoring the database volume and media folder from the same point in time, restoring `.env`, then starting the stack again.

## Observability

Basic logs:

```sh
docker compose logs -f app
docker compose logs -f worker
docker compose logs -f nginx
```

Optional Loki, Alloy, and Grafana services are included behind the `observability` profile:

```sh
COMPOSE_PROFILES=observability docker compose up -d
```

Grafana binds to `127.0.0.1:${GRAFANA_PORT:-3000}` by default.

## Development

Install dependencies in a virtual environment:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py test
```

Run Django locally:

```sh
python manage.py runserver
```

The Docker setup is the recommended path for anything beyond quick code changes because media processing depends on `ffmpeg`.

## What Not To Commit

Do not commit:

- `.env` or other private env files.
- Uploaded tracks.
- Mix covers.
- Profile pictures or banners.
- Processed audio or generated cover derivatives.
- SQLite databases.
- `local-media/`, `media/`, or `staticfiles/`.

The repo includes `.gitignore` and `.dockerignore` rules for these paths, but it is still worth checking `git status` before publishing.

## License

MixStream is licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
