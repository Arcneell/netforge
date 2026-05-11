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
FROM nginx:1.27-alpine AS runtime

# Drop default site, replace with our SPA + reverse-proxy config.
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/netforge.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
