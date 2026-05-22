# Deploy MixStream on a Debian Docker VM

This guide targets a small Debian VM running Docker Engine and the Docker Compose plugin. It keeps MixStream isolated from other stacks such as Jellystat and publishes only the nginx port to the LAN.

## Expected Shape

- Stack path: `/opt/stacks/mixstream`
- Compose project name: `mixstream`
- Public LAN URL for first boot: `http://<VM-IP>:8081`
- Published port: host `8081` to nginx container `8080`
- Postgres: internal Compose service only, no host port
- Worker: `python manage.py process_mix_media --sleep 45`
- Auth for first LAN boot: Django local account, with `OIDC_ENABLED=false`

## Prepare the VM

```sh
hostname -I
docker --version
docker compose version
docker ps --format "table {{.Names}}\t{{.Ports}}"
free -h
```

Create the stack directory:

```sh
sudo mkdir -p /opt/stacks/mixstream
sudo chown -R "$USER":"$USER" /opt/stacks/mixstream
cd /opt/stacks
```

Clone or copy the repo into `/opt/stacks/mixstream`:

```sh
git clone <repo-url> mixstream
cd /opt/stacks/mixstream
```

If the repo was copied another way, make sure `docker-compose.yml`, `Dockerfile`, `nginx/default.conf`, `manage.py`, `config/`, and `mixes/` are all in `/opt/stacks/mixstream`.

## Configure `.env`

Start from the VM template:

```sh
cp .env.vm.example .env
nano .env
```

Replace `<VM-IP>` with the VM LAN IP and generate secrets:

```sh
openssl rand -base64 32
openssl rand -base64 32
openssl rand -base64 32
```

For first boot, keep these values:

```env
DJANGO_DEBUG=true
OIDC_ENABLED=false
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<VM-IP>
DJANGO_CSRF_TRUSTED_ORIGINS=http://<VM-IP>:8081
NAS_MEDIA_PATH=/opt/stacks/mixstream/media
APP_PORT=8081
WEB_CONCURRENCY=2
```

Create the media directory:

```sh
mkdir -p /opt/stacks/mixstream/media
```

## Start the Stack

```sh
docker compose up -d --build
docker compose ps
```

The Compose file defaults to reading `.env`. If you want to test a template directly without copying it first, run:

```sh
MIXSTREAM_ENV_FILE=.env.vm.example docker compose --env-file .env.vm.example config
```

Follow logs:

```sh
docker compose logs -f db
docker compose logs -f app
docker compose logs -f worker
docker compose logs -f nginx
```

Open:

```text
http://<VM-IP>:8081
```

## Create a Local Admin User

With `OIDC_ENABLED=false`, the app login redirects to Django admin login. Create a superuser:

```sh
docker compose exec app python manage.py createsuperuser
```

Then open:

```text
http://<VM-IP>:8081/login/
```

## Smoke Tests

```sh
curl http://<VM-IP>:8081/health/
docker compose exec app python manage.py check
docker compose exec app python manage.py migrate --check
docker compose exec app python manage.py collectstatic --noinput
```

In the browser:

- Load the home page logged out.
- Log in with the local superuser.
- Upload a small test mix.
- Watch the worker logs until media processing completes.
- Confirm playback works and seeking works.

## Useful Operations

Restart one service:

```sh
docker compose restart app
docker compose restart worker
docker compose restart nginx
```

Run management commands:

```sh
docker compose exec app python manage.py shell
docker compose exec app python manage.py createsuperuser
docker compose exec worker python manage.py process_mix_media --failed --once
docker compose exec worker python manage.py process_mix_media --all --once
```

Inspect resources:

```sh
docker stats
docker system df
docker volume ls | grep mixstream
```

Stop the stack:

```sh
docker compose down
```

Reset the app data completely:

```sh
docker compose down -v
sudo rm -rf /opt/stacks/mixstream/media/*
```

Only run the reset commands if you are comfortable deleting all database and media data for this stack.

## Later: Reverse Proxy and Authentik

When you are ready to put Nginx Proxy Manager in front of the app:

1. Keep the Compose stack listening on `http://<VM-IP>:8081`.
2. Add an NPM proxy host pointing to `http://<VM-IP>:8081`.
3. Set `DJANGO_ALLOWED_HOSTS` to the hostname.
4. Set `DJANGO_CSRF_TRUSTED_ORIGINS=https://your-hostname`.
5. Set `SESSION_COOKIE_SECURE=true` and `CSRF_COOKIE_SECURE=true`.
6. Configure authentik and set `OIDC_ENABLED=true`.
7. Switch `DJANGO_DEBUG=false` only after all production values are filled in.

Production mode intentionally refuses placeholder secrets, missing OIDC settings, missing `DATABASE_URL`, wildcard hosts, or insecure cookies.
