# Build stage
FROM python:3.11-slim as builder

WORKDIR /build

# Install pip-tools for better dependency management
RUN pip install --no-cache-dir pip-tools

# Copy requirements first for better caching
COPY requirements.txt .

# Compile dependencies
RUN pip-compile --output-file=requirements-compiled.txt requirements.txt

# Install only the compiled dependencies
RUN pip install --no-cache-dir -r requirements-compiled.txt

# Production stage
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8081

# Create non-root user for security
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy only the necessary files
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY combined_server.py .
COPY login.html .
COPY webchat.html .
COPY .env.example .

# Create directory for vendor dependencies (if used)
RUN mkdir -p vendor

# Change ownership to non-root user
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Expose the port
EXPOSE 8081

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/')" || exit 1

# Run the application
CMD ["python", "combined_server.py"]
