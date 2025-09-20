# Use a lightweight Python base image
FROM python:3.11-slim

# Install system dependencies (LibreOffice + fonts + poppler for pdf2image)
RUN apt-get update && apt-get install -y \
    libreoffice \
    poppler-utils \
    fonts-dejavu \
    && apt-get clean

# Set working directory
WORKDIR /app

# Copy all project files into container
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port (Railway sets $PORT automatically)
EXPOSE 5000

# Start with Gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:${PORT}", "--workers", "3"]
