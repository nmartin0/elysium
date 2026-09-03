# Elysium web UI

A real client for the `api/` layer — login; ask a question (Query);
search and browse objects, with a real per-object detail page and
direct action invocation (Browse); approve or reject a proposed write;
and (for admins) manage user accounts. React + TypeScript + Vite, no
state management library, no design system — deliberately kept small
(see the main project README's "Two ways to run this" section for what
`api/` actually exposes).

An npm workspace, one package per real screen or shared concern, not
one monolithic app:

```
ui/src/                 App.tsx (auth state, routing, what's fetched
                         once and passed down), Shell.tsx (header/nav
                         chrome), main.tsx (entry point).
ui/packages/shell-api/  Shared across every screen: api.ts (the one
                         place that knows about fetch/session/CSRF),
                         format.ts (display-formatting helpers),
                         LoginForm, PendingWriteCard (the two-phase
                         write confirmation UI).
ui/packages/app-query/  QueryPanel -- the LLM question/answer screen.
ui/packages/app-browse/ ObjectSearchPanel (live, debounced search) and
                         ObjectDetailPanel (a real, bookmarkable
                         per-object page, with direct action
                         invocation via forms -- no LLM involved).
ui/packages/app-admin/  AdminPanel -- create/disable/enable/delete
                         users, inspect a user's own visible schema.
```

## Development

```bash
npm install
npm run dev
```

Every real backend path lives under `/api` — Vite's own dev-server
proxy forwards `/api/*` to a backend running on
`http://localhost:8000` by default; start that separately (e.g.
`uvicorn api.app:app` from the project root). Override the target with
`VITE_API_PROXY_TARGET` if your backend runs elsewhere:

```bash
VITE_API_PROXY_TARGET=http://localhost:9000 npm run dev
```

## Testing, linting, and type checking

```bash
npm test              # vitest -- the full suite, once
npm run lint          # oxlint, then tsc --noEmit (npm run typecheck alone)
npm run format:check  # oxfmt -- verify formatting without changing anything
npm run format        # oxfmt -- fix formatting in place
npm run knip          # unused files, exports, and dependencies
```

Five separate, genuinely different checks — style/correctness
(`oxlint`), does every type actually agree (`tsc --noEmit`), does
anything still use this file/export/dependency at all (`knip`), and
formatting (`oxfmt`), on top of the real, behavioral test suite
(`vitest`, exercising real user flows through React Testing Library,
not shallow rendering). `tsconfig.json`'s own comments explain the
specific compiler options chosen and why.

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

`packages/shell-api/src/api.ts` is the one place that knows about
headers, the session/CSRF cookies, and error shapes -- query/write
endpoints for every logged-in user, plus browse/search, per-object
detail, direct action invocation, and the admin account-management
endpoints (list/create/disable/enable/delete users, force-logout, the
visible-schema debug view), all gated server-side by whichever
grant actually applies -- this module never decides who's allowed to
call what. Relative paths throughout (`/login`, not a full URL) work
correctly in both dev (proxied) and production (same-origin, since the
backend serves this UI itself) without any environment-specific
configuration to keep in sync.
