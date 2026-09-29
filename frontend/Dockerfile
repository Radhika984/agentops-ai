FROM node:20-alpine

WORKDIR /app

# Install dependencies first (separate layer from app code) so code
# changes don't invalidate the dependency-install cache.
#
# `npm install`, not `npm ci`: Tailwind v4's platform-specific optional
# dependencies (native/wasm binaries) get resolved differently on the
# Windows host that generates package-lock.json than on this Linux
# container, which `npm ci`'s strict lockfile check rejects. `npm install`
# reconciles that instead of failing.
COPY package.json package-lock.json ./
RUN npm install

COPY . .

EXPOSE 3000

# Required so CI/orchestrators can tell "container running" apart from
# "container actually serving traffic" (see Phase 0 Common Mistakes).
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD node -e "fetch('http://localhost:3000').then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["npm", "run", "dev"]
