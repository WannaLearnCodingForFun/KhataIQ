FROM node:22-alpine AS build
# Next.js writes rewrites into the build output, so the API address is a build argument.
ARG KHATAIQ_API_URL=http://api:8000
ENV KHATAIQ_API_URL=$KHATAIQ_API_URL
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM node:22-alpine
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /web
RUN addgroup -S web && adduser -S web -G web
COPY --from=build --chown=web:web /web/.next/standalone ./
COPY --from=build --chown=web:web /web/.next/static ./.next/static
USER web
EXPOSE 3000
CMD ["node", "server.js"]
