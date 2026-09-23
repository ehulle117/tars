FROM python:3.12-alpine
WORKDIR /app
RUN apk add --no-cache curl
COPY . .
# Placeholder files so k8s subPath mounts onto an empty PVC create regular
# files, not directories (kubelet matches the type already present here).
RUN touch state.json adsb_tools.db photo_cache.json
