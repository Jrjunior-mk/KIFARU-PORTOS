# KIFARU PORTOS web — multi-stage build: Vite bundle -> nginx serving the SPA with /api and /ws proxied to the API.
#
#   docker build -t kifaru-web --build-arg VITE_API_BASE= .
#   docker run -p 8080:80 -e API_UPSTREAM=http://api:8000 kifaru-web
#
# VITE_API_BASE stays empty so the browser calls same-origin /api, which nginx forwards to $API_UPSTREAM.

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_API_BASE=
ARG VITE_WS_BASE=
ENV VITE_API_BASE=$VITE_API_BASE VITE_WS_BASE=$VITE_WS_BASE
RUN npm run build

FROM nginx:1.27-alpine AS runtime
ENV API_UPSTREAM=http://api:8000
ENV NGINX_PORT=80
# envsubst runs on templates in /etc/nginx/templates at container start (official image entrypoint).
COPY nginx/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:${NGINX_PORT}/healthz || exit 1
