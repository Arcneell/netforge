# syntax=docker/dockerfile:1.7

# ---------- Build stage ----------
# Node 22 = active LTS and the version CI tests against (Node 20 hit EOL
# April 2026 — building on a runtime the test matrix never sees is asking
# for drift).
FROM node:22-alpine AS build
WORKDIR /app

# Install deps separately so npm cache layer survives source-only changes.
# `npm ci` only, no `|| npm install` fallback: a lockfile out of sync with
# package.json must fail the build loudly instead of silently resolving a
# fresh (untested) dependency tree into the production image.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Production build (vue-tsc + vite build). Outputs to /app/dist.
RUN npm run build

# ---------- Runtime stage ----------
# Unprivileged variant: the whole nginx process tree (master included) runs
# as the non-root `nginx` user (UID 101). A container escape or nginx RCE
# lands in an unprivileged account instead of root. Consequence: non-root
# can't bind ports <1024, so the image listens on 8080/8443 instead of
# 80/443 — the nginx configs and the port mappings in docker-compose.yml
# are aligned with that.
FROM nginxinc/nginx-unprivileged:1.31-alpine AS runtime

# Drop the stock site, install our SPA + reverse-proxy config. The image
# ships with the TLS-terminating prod config by default — the HTTP-only
# nginx.conf is kept alongside for deployments behind an external proxy
# (Traefik / Caddy / nginx-proxy-manager). Switch by overriding the file
# at /etc/nginx/conf.d/netforge.conf via a bind mount.
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.prod.conf /etc/nginx/conf.d/netforge.conf
COPY nginx.conf      /etc/nginx/conf.d/netforge.http.conf.disabled

COPY --from=build /app/dist /usr/share/nginx/html

# Unprivileged listen ports (see runtime-stage note above). Host-facing
# 80/443 are restored by the port mappings in docker-compose.yml.
EXPOSE 8080 8443
CMD ["nginx", "-g", "daemon off;"]
