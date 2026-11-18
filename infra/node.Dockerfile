FROM node:24.22.3-bookworm-slim
WORKDIR /app
RUN npm install --global pnpm@12.21.0
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY gateway/package.json ./gateway/package.json
COPY apps/web/package.json ./apps/web/package.json
RUN --mount=type=cache,id=radar-pnpm,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY gateway ./gateway
COPY packages ./packages
COPY apps/web ./apps/web
COPY tests ./tests
COPY codegen.ts playwright.config.ts playwright.partial.config.ts eslint.config.mjs .prettierrc.json .prettierignore ./

