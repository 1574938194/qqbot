ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1     OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false     HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
WORKDIR /srv/gpt-sovits
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN sed -i 's|http://deb.debian.org/debian-security|https://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources && apt-get -o Acquire::Retries=2 -o Acquire::https::Timeout=30 update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 libgomp1 gcc g++ make && rm -rf /var/lib/apt/lists/*
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install torch==2.6.0+cpu torchaudio==2.6.0+cpu --index-url ${TORCH_INDEX_URL} --extra-index-url ${PIP_INDEX_URL}
COPY requirements-cpu.lock /tmp/requirements-cpu.lock
ARG PIP_EXTRA_INDEX_URL=
RUN pip install -r /tmp/requirements-cpu.lock
COPY source/ ./
COPY tts.yaml /etc/gsv/tts.yaml
COPY serve.py ./serve.py
COPY bert_onnx.py ./bert_onnx.py
COPY fixed_voice.py ./fixed_voice.py
EXPOSE 9880
CMD ["python", "serve.py"]
