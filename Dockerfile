# Use a lightweight Python base image
FROM python:3.11-slim

# Install system dependencies (LibreOffice + fonts + poppler for pdf2image)
RUN apt-get update && apt-get install -y \
    libreoffice \
    poppler-utils \
    fonts-dejavu \
    qpdf \
    && apt-get clean

# Set working directory
WORKDIR /app

# Copy all project files into container
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Make start script executable and use it as entrypoint so $PORT is handled by the shell shebang.
RUN chmod +x start.sh

# Expose the port (Railway sets $PORT automatically)
EXPOSE 5000

# Use the start script (shebang will run /bin/bash and expand $PORT). This avoids the JSON-array expansion issue.
ENTRYPOINT ["./start.sh"]
