# Security

This screen is a local-first client for **public** data. It is a development
and preview server (Vite) with data routes in `server/providers/`, not a
hardened production service. Astrolabe's plan puts the data behind Elysium;
until then, this is the security model of the screen as it runs.

## Reporting

Report problems with the Astrolabe fork privately to the Elysium maintainers,
not in a public issue. For a flaw in the upstream God's Eye View code that also
exists upstream, the upstream project takes private reports through GitHub
(<https://github.com/bilawalsidhu/gods-eye-view>, Security tab).

## Keys

Secrets stay on the server. The server brokers every request that needs a
private credential, so the browser never receives one.

| Key | Where | Use |
| --- | --- | --- |
| `AISSTREAM_API_KEY` | Server only | The server holds the AISStream websocket; the browser polls `/api/vessels` |
| `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET` | Server only | The server mints and refreshes the token behind `/api/flights` |
| `FIRMS_MAP_KEY` | Server only | Behind `/api/firms` |
| `LL2_API_TOKEN` | Server only | Launch Library 2 |
| `GOOGLE_MAPS_SERVER_API_KEY` | Server only | Places and Geocoding proxies (`/api/google/*`); falls back to the browser key when unset |

Two keys are **deliberately in the browser** and visible in devtools, so
restrict them at the provider: `GOOGLE_MAPS_API_KEY` (HTTP referrer plus API
restriction) and `CESIUM_ION_TOKEN` (a public-assets token). The explicit
`define` block in `build/vite.js` sets what reaches the client bundle; it
still also injects `MAPILLARY_CLIENT_TOKEN` although the Mapillary feature is
gone (to be removed from the build config).

Never commit real keys: `.env` is ignored and only `.env.example` is tracked.
The dev server denies `.env*`, certificates, `.git`, `.gev-logs/` and
`.gev-cache/` to file requests.

## Server routes

- Proxies fetch fixed upstreams or server-registered ones (for example transit
  feeds are resolved from `src/data/transitFeeds.js`); the browser never
  supplies an upstream URL.
- Every `/api` response, including errors and unknown routes, carries
  `Content-Security-Policy: default-src 'none'; sandbox` and
  `X-Content-Type-Options: nosniff`. An unknown `/api/*` path gets a JSON 404.
- Responses are size-capped and time-limited, errors are sanitised, and
  OpenSky token refresh is coalesced.
- The Google cost endpoints (`/api/google/nearby-places`,
  `/api/google/text-search`) are rate limited per client
  (`GEV_RATELIMIT_GOOGLE_PER_MIN`, default 120).
- Pages carry a Content-Security-Policy and `X-Frame-Options: DENY`
  (`BROWSER_CSP` in `build/vite.js`). That policy still allows
  `'unsafe-eval'` and `maps.googleapis.com` scripts, left over from upstream;
  FORK.md records that the app runs without `unsafe-eval`.
- `?embed=1` pages are not framable unless `GEV_EMBED_FRAME_ANCESTORS` names
  the pages that may frame them.

## Network exposure

The server is a key broker: every server key is spendable by anyone who can
reach it. It binds to `localhost` by default and accepts only the hosts in
`localhost`, `127.0.0.1`, IP addresses, and the names in `GEV_ALLOWED_HOSTS`.
Setting `HOST=0.0.0.0` exposes it to the network; do that only behind your own
authentication, and set budgets and quotas with the providers as the real
spend limit.

## Use

All data shown is public. Follow each provider's terms and rate limits
([DATA_SOURCES.md](DATA_SOURCES.md)), and do not present public-data
inference as authoritative.
