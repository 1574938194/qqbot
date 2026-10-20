ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1
WORKDIR /app
ARG SYSTEM_DEPS=1
RUN if [ "$SYSTEM_DEPS" = 1 ]; then apt-get update && apt-get install -y --no-install-recommends gcc g++ make libgomp1 && rm -rf /var/lib/apt/lists/*; fi
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_EXTRA_INDEX_URL=
COPY requirements.lock ./requirements.lock
RUN pip install -r requirements.lock && python -c "import importlib.util; assert importlib.util.find_spec('torch') is None"
COPY source/genie_tts ./genie_tts
COPY source/LICENSE ./GENIE-LICENSE
COPY engine.py server.py ./
EXPOSE 9880
CMD ["python", "server.py"]
