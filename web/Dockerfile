FROM node:24-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

FROM node:24-alpine AS builder
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production WRANGLER_LOG_PATH=.wrangler/wrangler.log
COPY --from=builder /app ./
EXPOSE 3000
CMD ["./node_modules/.bin/vinext", "start", "--host", "0.0.0.0"]
