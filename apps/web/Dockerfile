FROM node:20-slim AS build
WORKDIR /app
COPY apps/web/package.json ./
RUN npm install
COPY apps/web/ ./
# NEXT_PUBLIC_* değerleri build sırasında pakete gömülür; runtime `environment:` ile DEĞİŞTİRİLEMEZ.
# Boş (varsayılan) = tarayıcı aynı kökene `/api/...` ile gider (Nginx → API). Yalnızca ayrı bir API alan adı için doldurun.
ARG NEXT_PUBLIC_API_BASE_URL=""
# Next.js sunucusunun `/api` isteklerini aktaracağı, Docker ağı içindeki API adresi (yalnızca yedek yol; bkz. next.config.mjs).
ARG API_INTERNAL_URL="http://api:8000"
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    API_INTERNAL_URL=$API_INTERNAL_URL
RUN npm run build

FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/package.json ./
COPY --from=build /app/node_modules ./node_modules
CMD ["npm", "start"]
