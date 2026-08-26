# Elysium web UI

A minimal, real client for the `api/` layer — login, ask a question,
approve or reject a proposed write, and (for admins) manage user
accounts. Plain React + Vite, no state management library, no design
system — deliberately kept small (see the main project README's "Two
ways to run this" section for what `api/` actually exposes).

## Development

```bash
npm install
npm run dev
```

Requests to the real API paths (`/login`, `/query`, `/writes/*`, etc.)
are proxied straight through to a backend running on
`http://localhost:8000` by default — start that separately (e.g.
`uvicorn api.app:app` from the project root). Override the target with
`VITE_API_PROXY_TARGET` if your backend runs elsewhere:

```bash
VITE_API_PROXY_TARGET=http://localhost:9000 npm run dev
```

## Production

```bash
npm run build
```

Produces `dist/` — `api/app.py` serves this automatically, from the
same process as the API itself, if it exists (see that file's own
docstring). `install/install.sh` runs this build step automatically
during a fresh install, if `npm` is available; it's skipped gracefully
otherwise, and the backend still runs correctly as an API-only
deployment either way.

## Why plain fetch(), no API client library

`src/api.js` is the one place that knows about headers, the token, and
error shapes -- query/write endpoints for every logged-in user, plus
the admin account-management endpoints (list/create/disable/enable/
delete users, force-logout, the visible-schema debug view), all gated
server-side by manage:users -- this module never decides who's allowed
to call what. Relative paths throughout (`/login`, not a full URL)
work correctly in both dev (proxied) and production (same-origin,
since the backend serves this UI itself) without any environment-
specific configuration to keep in sync.
