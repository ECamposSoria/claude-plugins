FROM python:3.12.12-slim-bookworm

# cpu = the VM image; cu128 = the laptop's RTX 4070 (docker-compose.gpu.yml)
ARG TORCH_FLAVOR=cpu

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --index-url "https://download.pytorch.org/whl/${TORCH_FLAVOR}" \
      "torch==2.11.0+${TORCH_FLAVOR}" "torchaudio==2.11.0+${TORCH_FLAVOR}"
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# uid 1000 = the VM user (and the laptop's WSL user), so files written to the mounted folder stay editable.
# /models becomes the named volume: a new volume copies this ownership.
RUN useradd -u 1000 -m listener && mkdir -p /models /work && chown listener /models /work
USER listener
# Whisper's ctranslate2 loads cuBLAS/cuDNN from the CUDA torch wheels; the paths do not exist on the cpu image.
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib \
    HF_HOME=/models/hf TORCH_HOME=/models/torch XDG_CACHE_HOME=/models/cache \
    NUMBA_CACHE_DIR=/tmp/numba PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /work
ENTRYPOINT ["python", "-I"]
