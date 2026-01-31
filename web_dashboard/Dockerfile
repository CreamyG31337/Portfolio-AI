# Streamlit Dashboard Dockerfile
# Uses python:3.11-slim to match existing containers on the server
# Includes APScheduler for background tasks
# Uses shared frontend builder (trading-dashboard-frontend:latest)

# Stage 1 is removed - use shared frontend-builder image
# Use shared base image with common Python dependencies
FROM trading-dashboard-base:latest

# Copy entire project (cleaner than selective copying)
COPY . /app

# Copy built frontend assets from shared builder
# Ensure directory exists first, then copy the built files
RUN mkdir -p web_dashboard/static/css web_dashboard/static/js
COPY --from=trading-dashboard-frontend:latest /app/web_dashboard/static/css/tailwind.css ./web_dashboard/static/css/
COPY --from=trading-dashboard-frontend:latest /app/web_dashboard/static/js/ ./web_dashboard/static/js/
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

