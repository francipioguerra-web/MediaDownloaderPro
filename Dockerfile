# Lightweight container for StreamingCommunity Watch Party Hub on Render
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000

# Install minimal dependencies for Watch Party Hub (super fast build)
COPY requirements_watchparty.txt .
RUN pip install --no-cache-dir -r requirements_watchparty.txt

# Copy application files (including user_data_seed/)
COPY . .

EXPOSE 10000

# Start Gunicorn binding to $PORT provided by Render
CMD ["sh", "-c", "gunicorn watchparty_server:app --bind 0.0.0.0:${PORT:-10000} --workers 2 --threads 4 --timeout 120"]
