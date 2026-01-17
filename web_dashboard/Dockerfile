# Streamlit Dashboard Dockerfile
# Uses python:3.11-slim to match existing containers on the server
# Includes APScheduler for background tasks
# Multi-stage build: Build Tailwind CSS first, then Python app

# Stage 1: Build Tailwind CSS
FROM node:20-alpine AS tailwind-builder
WORKDIR /app

# Copy package files for dependency installation (better layer caching)
COPY package.json ./
COPY tailwind.config.js ./

# Install npm dependencies (cached layer - only rebuilds if package.json changes)
# Use BuildKit cache mount to persist npm cache between builds
RUN --mount=type=cache,target=/root/.npm \
    npm install

# Copy Tailwind input CSS and source files needed for content scanning
# Copy in order: config, input CSS, then templates (for better caching)
COPY web_dashboard/static/css/input.css ./web_dashboard/static/css/input.css
COPY web_dashboard/templates ./web_dashboard/templates
# Copy TypeScript source and config
COPY web_dashboard/tsconfig.json ./web_dashboard/tsconfig.json
COPY web_dashboard/src ./web_dashboard/src

# Build Tailwind CSS (production-optimized, minified) and TypeScript
# Ensure output directories exist and build with error handling
RUN mkdir -p web_dashboard/static/css web_dashboard/static/js && \
    npm run build:css && \
    echo "=== TypeScript Compilation Starting ===" && \
    npm run build:ts || \
    (echo "=== TypeScript Compilation Failed ===" && \
     echo "Showing compilation diagnostics:" && \
     (cd web_dashboard && npx tsc --diagnostics 2>&1 || true) && \
     echo "=== Full TypeScript Error Output ===" && \
     exit 1) && \
    echo "=== TypeScript Compilation Successful ===" && \
    ls -lh web_dashboard/static/css/tailwind.css || \
    (echo "ERROR: Tailwind CSS build failed - output file not found" && exit 1)

# Stage 2: Python app
# Use shared base image with common Python dependencies
FROM trading-dashboard-base:latest

# Copy entire project (cleaner than selective copying)
COPY . /app

# Copy built Tailwind CSS and compiled JS from builder stage
# Ensure directory exists first, then copy the built files
RUN mkdir -p web_dashboard/static/css web_dashboard/static/js
COPY --from=tailwind-builder /app/web_dashboard/static/css/tailwind.css ./web_dashboard/static/css/tailwind.css
COPY --from=tailwind-builder /app/web_dashboard/static/js ./web_dashboard/static/js
RUN test -f web_dashboard/static/css/tailwind.css || (echo "ERROR: Tailwind CSS file not found after copy from builder stage" && exit 1)

# PYTHONPATH is already set in base image

# Expose Streamlit port
EXPOSE 8501

# Health check - handles connection errors gracefully
# (healthcheck.py is already copied via COPY . /app above)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python /app/web_dashboard/healthcheck.py

# Run via entrypoint (starts scheduler + Streamlit)
CMD ["python", "web_dashboard/entrypoint.py"]

