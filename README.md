# NestHost - free static hosting + free subdomains (Hostinger-style)

Users sign up, claim `name.yourdomain.com` for free, upload a ZIP (or publish a ready template) and the site is live,
with automatic HTTPS and optional custom-domain connect. Flask + SQLite + Caddy, runs in Docker.

## Honest note about domains
No app can register real `.com/.in` domains for free (registries charge fees). NestHost gives free **subdomains of a domain you own**.
Cheapest route: buy one domain (often a few hundred rupees/year on sale) and use it as `BASE_DOMAIN`. For zero-cost demos use `localhost` or `<ip-with-dashes>.sslip.io`.

## Run locally (no domain, no Docker)
    python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
    python -m unittest discover -s tests
    PUBLIC_PORT=:8000 flask --app nesthost.app:wsgi run -p 8000
    # open http://localhost:8000  ->  your site appears at http://yourname.localhost:8000 (browsers resolve *.localhost)

## Deploy on EC2 (Docker)
1. Install Docker + compose plugin. Security Group: 22, 80, 443.
2. `cp .env.example .env` and edit (`BASE_DOMAIN`, `SERVER_IP`, `ADMIN_EMAIL`).
3. **DNS** at your registrar: `A @ -> server IP` and `A * -> server IP` (wildcard).
   Demo without a domain: `BASE_DOMAIN=13-233-1-2.sslip.io`, `PUBLIC_SCHEME=http`, `CADDYFILE=Caddyfile.http`.
4. `docker compose up -d --build` then open `https://yourdomain.com`. First signup becomes admin.

HTTPS: Caddy issues a certificate on the first visit to each hostname, only if `/internal/tls-check` approves it.
Let's Encrypt allows ~50 new certificates per week per registered domain; for a big platform switch to a wildcard certificate (DNS challenge plugin for your DNS provider).

## Jenkins + GitHub
Create `/opt/nesthost/.env` on the server, give the `jenkins` user docker + write access to `/opt/nesthost`, then Pipeline from SCM (`Jenkinsfile`).
GitHub Actions (`.github/workflows/ci.yml`) runs tests and a container health check on every push.

## Security model (read before going public)
- User sites live on subdomains of your domain. Session cookie is host-only (`__Host-` prefix on HTTPS) so a user site cannot read or override it. Forms are CSRF-protected.
- Only static files are served (no PHP/Node). ZIPs are extracted safely: no `..` paths, no symlinks, extension whitelist, size and file-count limits.
- Free hosting attracts phishing. Keep `ADMIN_EMAIL` set (footer abuse link) and use `/admin` to suspend sites. Consider adding your domain to the Public Suffix List.
- Rate limits are in-memory per process; put Cloudflare or similar in front for real traffic.
