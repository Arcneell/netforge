# syntax=docker/dockerfile:1.7

# ---------- Build stage ----------
FROM node:20-alpine AS build
WORKDIR /app

# Install deps separately so npm cache layer survives source-only changes.
COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .

# Production build (vue-tsc + vite build). Outputs to /app/dist.
RUN npm run build

# ---------- Runtime stage ----------
FROM nginx:1.31-alpine AS runtime

# Drop the stock site, install our SPA + reverse-proxy config. The image
# ships with the TLS-terminating prod config by default — the HTTP-only
# nginx.conf is kept alongside for deployments behind an external proxy
# (Traefik / Caddy / nginx-proxy-manager). Switch by overriding the file
# at /etc/nginx/conf.d/netforge.conf via a bind mount.
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.prod.conf /etc/nginx/conf.d/netforge.conf
COPY nginx.conf      /etc/nginx/conf.d/netforge.http.conf.disabled

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]
