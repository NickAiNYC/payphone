# Use nvidia/cuda runtime for optional CUDA acceleration
FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

# Install python and system audio dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    espeak-ng \
    git \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set python3 as default
RUN ln -s /usr/bin/python3 /usr/bin/python

WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy source code and config
COPY . .
RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]

