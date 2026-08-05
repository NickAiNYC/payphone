# Use nvidia/cuda runtime for optional CUDA acceleration
FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

# Install python and system audio dependencies
# --no-install-recommends keeps this to what is actually needed. Without it the
# build pulls ~265 MB of transitive packages, and a fetch that long can outlive
# its own index: Ubuntu supersedes a package mid-download and apt 404s on a
# filename it just read as current. The retry covers the residual race.
RUN for attempt in 1 2 3; do \
        apt-get update && apt-get install -y --no-install-recommends \
            python3 \
            python3-pip \
            ffmpeg \
            espeak-ng \
            git \
            curl \
        && break || { echo "apt attempt $attempt failed, retrying"; sleep 5; }; \
    done \
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

