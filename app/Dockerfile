# App image: runs the ingestion / query CLI against the PostgreSQL and
# ChromaDB service containers.
FROM python:3.11-slim

WORKDIR /app

# Install deps first so Docker can cache this layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY . .

# Run the FastAPI web server. The CLI (cli.py) still works via
# `docker compose exec app python cli.py ...` for debugging.
EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
