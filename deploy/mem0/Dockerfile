FROM xiaoai-qqbot:qwenpaw-gateway
USER root
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.lock /opt/qqbot-mem0/requirements.lock
RUN python -m venv --system-site-packages /opt/mem0-venv && /opt/mem0-venv/bin/pip install --no-cache-dir --index-url ${PIP_INDEX_URL} -r /opt/qqbot-mem0/requirements.lock
COPY server.py /opt/qqbot-mem0/server.py
ENV HOME=/state MEM0_TELEMETRY=false ANONYMIZED_TELEMETRY=false HF_ENDPOINT=https://hf-mirror.com FASTEMBED_CACHE_PATH=/state/models OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
WORKDIR /opt/qqbot-mem0
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:32129/health',timeout=3)"
ENTRYPOINT ["/opt/mem0-venv/bin/python", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "32129", "--no-access-log", "--log-level", "warning"]
