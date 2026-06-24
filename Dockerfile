FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# ── Install PyTorch CPU-only FIRST ───────────────────────────
# This MUST come before requirements.txt. If we let pip resolve
# torch from requirements.txt, it pulls the CUDA version which
# downloads 2.5GB of NVIDIA libraries we don't need.
# CPU-only torch is ~150MB instead.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# ── Install remaining dependencies ───────────────────────────
# Since torch is already installed (CPU), pip will skip it and
# sentence-transformers will use the existing CPU torch.
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ── Pre-download embedding model at build time ──────────────
# Same model used by ingestion. Downloaded once during build
# so the container never needs to reach HuggingFace at runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('all-MiniLM-L6-v2')"

ENV TRANSFORMERS_OFFLINE=1
ENV HF_HUB_OFFLINE=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]