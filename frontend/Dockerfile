# ── Stage 1: build ──────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

# Зависимости — отдельный слой. Пересобирается только при изменении package*.json.
COPY package*.json ./
RUN npm ci --prefer-offline

COPY . .

# VITE_API_BASE_URL — намеренно относительный путь /api/v1, не абсолютный.
# Причина: nginx в этом же образе проксирует /api/ → app:8000.
# Если бы URL был абсолютным (https://support.company.com/api/v1), образ
# нужно было бы пересобирать под каждый хост заказчика. Относительный путь
# работает на любом хосте без пересборки.
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_API_TIMEOUT_MS=210000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_API_TIMEOUT_MS=$VITE_API_TIMEOUT_MS

RUN npm run build

# ── Stage 2: serve ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Собранный SPA в корень nginx
COPY --from=builder /app/dist /usr/share/nginx/html

# Наш конфиг: SPA fallback + proxy /api/ + кэш статики
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
