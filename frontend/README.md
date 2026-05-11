# NetForge — Frontend

Vue 3 + TypeScript + Vite + Tailwind + Pinia SPA for the NetForge IPAM.

## Stack

- **Vue 3** (Composition API, `<script setup>`)
- **TypeScript** strict
- **Vite** dev server + build
- **Vue Router 4** with route-level auth guard
- **Pinia** for state
- **vue-i18n** for FR/EN translations
- **Tailwind CSS** with semantic CSS variables (light + dark themes)
- **Axios** HTTP client with shared error handling
- **lucide-vue-next** icons
- **openapi-typescript** generates TS types from the FastAPI OpenAPI schema

## Setup

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

The dev server runs on http://localhost:5173 and proxies `/api/*` to
`VITE_BACKEND_URL` (default `http://localhost:8000`). Start the backend
first (`docker compose -f ../docker-compose.dev.yml up -d`).

### Generate API types

Once the backend is reachable on `http://localhost:8000`:

```bash
npm run gen:types
```

This overwrites `src/api/schema.d.ts` with the typed contract derived from
`/api/openapi.json`. Re-run after any backend route or schema change.

## Scripts

| Command | What it does |
|---------|--------------|
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | `vue-tsc --noEmit` + production build to `dist/` |
| `npm run preview` | Serve the built `dist/` locally |
| `npm run type-check` | Type-check only |
| `npm run lint` | ESLint + auto-fix |
| `npm run format` | Prettier on `src/**` |
| `npm run gen:types` | Regenerate `src/api/schema.d.ts` from the backend OpenAPI spec |

## Layout

```
src/
├── api/            # axios client, generated schema, typed endpoint wrappers
├── assets/         # tailwind.css + design tokens
├── components/     # AppShell, AppSidebar, AppTopbar, ThemeToggle, ui primitives
├── composables/    # useApi, useAuth, useTheme, useToast, useDebounce
├── i18n/           # vue-i18n setup, en.json + fr.json locales
├── router/         # routes + auth guard
├── stores/         # Pinia: auth, ui
├── views/          # Route components
├── App.vue
├── main.ts
└── env.d.ts
```

## Theming

Two themes (light + dark) and a "system" mode are exposed via the topbar
toggle. Colors are CSS variables (`--color-bg`, `--color-surface`,
`--color-fg`, etc.) defined on `:root` and `.dark`, then bridged to
Tailwind through `tailwind.config.js`. Components use semantic classes
(`bg-bg`, `text-fg`, `border-border`, `text-primary-600`, …), so no
`dark:` prefixes are needed inside templates.

The selected theme is persisted in `localStorage` and applied before
first paint via a tiny inline script in `index.html` to avoid a flash
of the wrong palette.

## i18n

Locales live in `src/i18n/locales/` (`en.json`, `fr.json`). The current
locale is auto-detected from the browser on first visit and persisted
in `localStorage`. Switch from the topbar.

When adding a string, edit **both** locale files; keys not yet translated
fall back to English.

## Auth flow

1. SPA boots → `useAuthStore.fetchMe()` calls `GET /api/auth/me`.
2. If 401: router guard redirects unauthenticated users to `/login?next=<path>`.
3. `LoginView` button hits `GET /api/auth/login` via a top-level navigation,
   which 302s to the configured IdP (GitHub or generic OIDC).
4. IdP → backend `/api/auth/callback` → session cookie set → 302 to `/`.
5. SPA re-fetches `/me`, lands the user on `next` (if any) or dashboard.

The cookie is `HttpOnly`, `SameSite=Lax`, `Secure` in production. The SPA
never sees the session token; `axios` is configured with
`withCredentials: true` so the browser ships the cookie automatically.

## Production build

```bash
docker build -t netforge-frontend ./frontend
```

The image bundles the static SPA + an nginx config that:
- Serves the SPA with proper cache headers and HTML5 history fallback.
- Reverse-proxies `/api/*` to the backend container (service name: `backend`).
- Sets a strict CSP and the rest of the headers from `docs/11-security.md`.
