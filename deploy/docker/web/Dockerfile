ARG NODE_IMAGE=public.ecr.aws/docker/library/node:20.20.2-alpine

FROM ${NODE_IMAGE} AS build
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM ${NODE_IMAGE} AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    DUDUDA_WEB_BIND=0.0.0.0 \
    DUDUDA_WEB_INTERNAL_PORT=8000 \
    DUDUDA_WEB_PUBLIC_DIR=/app/dist \
    DUDUDA_ONEBOT_TOKEN_FILE=/run/secrets/onebot_access_token
COPY --from=build --chown=node:node /app/dist ./dist
COPY --from=build --chown=node:node /app/dist-server ./dist-server
USER node
EXPOSE 8000
CMD ["node", "dist-server/index.cjs"]
