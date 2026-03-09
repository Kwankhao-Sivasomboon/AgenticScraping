# Use the official Python 3.11 slim image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install system dependencies required for Playwright (headless Chromium)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy requirement files first (to leverage Docker layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install -r requirements.txt

# Install Playwright browser and its OS dependencies
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy all the source code into the container
COPY . .

# Set environment variable for PYTHONPATH to find modules in src/
ENV PYTHONPATH="${PYTHONPATH}:/app/src"

# Expose the port used by the server
EXPOSE 8080

# Run the server using uvicorn
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-keep-alive", "600"]
