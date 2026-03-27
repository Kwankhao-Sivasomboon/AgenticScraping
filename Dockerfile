FROM python:3.10-slim

WORKDIR /app

# Install system dependencies if required for Pillow/ImageHash
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code (using .dockerignore to skip .git and virtual environments)
COPY . /app/

# Expose Cloud Run default Port 8080
EXPOSE 8080

# Run FastAPI via Uvicorn Worker
CMD ["uvicorn", "main_api:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
