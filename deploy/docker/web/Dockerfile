ARG NODE_IMAGE=public.ecr.aws/docker/library/node:22.18.0-alpine

FROM ${NODE_IMAGE} AS build
WORKDIR /workspace/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
COPY configs/personas/registry-v1/ /workspace/configs/personas/registry-v1/
RUN npm run build

FROM ${NODE_IMAGE} AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    DUDUDA_WEB_BIND=0.0.0.0 \
    DUDUDA_WEB_INTERNAL_PORT=8000 \
    DUDUDA_WEB_PUBLIC_DIR=/app/dist \
    DUDUDA_ONEBOT_TOKEN_FILE=/run/secrets/onebot_access_token \
    DUDUDA_ASTRBOT_PLUGIN_API_KEY_FILE=/run/secrets/astrbot_plugin_api_key
COPY --from=build --chown=node:node /workspace/apps/web/dist ./dist
COPY --from=build --chown=node:node /workspace/apps/web/dist-server ./dist-server
USER node
EXPOSE 8000
CMD ["node", "dist-server/index.cjs"]
