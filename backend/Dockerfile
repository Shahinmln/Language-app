# TaleTalk backend — production image for Render / Docker
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Run with Gunicorn + Uvicorn worker (production)
EXPOSE 5000
CMD ["gunicorn", "--bind=0.0.0.0:5000", "--reuse-port", "-k", "uvicorn.workers.UvicornWorker", "main:app"]
