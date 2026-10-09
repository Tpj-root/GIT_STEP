FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# No VITE_API: the bundle uses same-origin URLs and nginx proxies to the
# backend, so one image runs on any host and port without a rebuild.
RUN npm run build

FROM nginx:alpine
ENV BACKEND_ORIGIN=http://backend:8010
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
