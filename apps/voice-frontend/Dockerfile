FROM node:22-bookworm-slim AS dependencies

WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/voice-frontend/package.json apps/voice-frontend/package.json
COPY packages/voice-ui/package.json packages/voice-ui/package.json
RUN npm ci

FROM dependencies AS builder

ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_INTERVIEW_CAMERA_ENABLED=false
ENV NEXT_PUBLIC_INTERVIEW_CAMERA_ENABLED=${NEXT_PUBLIC_INTERVIEW_CAMERA_ENABLED}

COPY apps/voice-frontend/ apps/voice-frontend/
COPY packages/voice-ui/ packages/voice-ui/
RUN npm run build --workspace voice-frontend

FROM node:22-bookworm-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /app
RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/apps/voice-frontend/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/voice-frontend/.next/static ./apps/voice-frontend/.next/static
COPY --from=builder --chown=nextjs:nodejs /app/apps/voice-frontend/public ./apps/voice-frontend/public

USER nextjs
EXPOSE 3000

CMD ["node", "apps/voice-frontend/server.js"]
