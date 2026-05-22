# Security Policy

## Supported Versions

MixStream is an early self-hosted project. Until the project reaches a stable
release, security fixes are expected to land on the default branch.

## Reporting a Vulnerability

Please do not open a public issue for sensitive security reports.

For now, contact the maintainer through GitHub:

<https://github.com/oliver-louis/mixstream>

If GitHub private vulnerability reporting is enabled for the repository, use
that first.

## Secrets

Never commit private deployment files or credentials:

- `.env`
- database passwords
- `DJANGO_SECRET_KEY`
- OIDC client secrets
- Grafana/admin passwords
- database dumps

The example env files are safe templates and must not contain real secrets.

## Media Privacy

Audio playback is permission-checked by Django and served through nginx with
`X-Accel-Redirect`. Direct access to `/media/mixes/` is denied by the bundled
nginx config.

Cover art, profile pictures, and banners are served as public static media if
someone knows the URL. Do not upload images there that must remain secret.

## Deployment Notes

For public deployments:

- Run with `DJANGO_DEBUG=false`.
- Use HTTPS at your reverse proxy.
- Use secure cookies.
- Keep Postgres internal to Docker Compose unless you have a specific reason.
- Back up the Postgres volume and media folder together.
