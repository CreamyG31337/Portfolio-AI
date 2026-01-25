# MCP HTTP Bridge Dockerfile
FROM node:22-slim

WORKDIR /app

# Install wget for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm install && npm cache clean --force

# Copy source code
COPY src ./src
COPY tsconfig.json* ./

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health 2>/dev/null || \
      curl -f http://localhost:8080/health 2>/dev/null || exit 1

# Run with tsx
CMD ["npx", "tsx", "src/index.ts"]
