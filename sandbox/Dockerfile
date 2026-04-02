FROM node:20-slim

# Install Python, git, and system deps for Playwright
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    ca-certificates \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Install Playwright and Chromium browser
RUN npm install -g playwright && playwright install chromium --with-deps

# Set up Python venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install harness Python deps
WORKDIR /harness
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy harness control plane (workspace/ is mounted at runtime)
COPY harness.yaml .
COPY ARCHITECTURE.md .
COPY SPEC.md .
COPY core/ core/
COPY docs/ docs/

# workspace/ is mounted as a volume at runtime:
#   docker run -v $(pwd)/workspace:/harness/workspace harnesslab
VOLUME ["/harness/workspace"]

# Phase 2: no Python orchestrator loop; keep container alive for mounted workspace / Claude Code.
CMD ["tail", "-f", "/dev/null"]
