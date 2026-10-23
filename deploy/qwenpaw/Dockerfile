ARG DSH_IMAGE=xiaoai-dsh:node-browser-health
FROM ${DSH_IMAGE}
USER root
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.lock /opt/qqbot-qwenpaw/requirements.lock
RUN python -m venv /opt/qwenpaw-venv \
    && /opt/qwenpaw-venv/bin/pip install --no-cache-dir --timeout 90 --index-url ${PIP_INDEX_URL} -r /opt/qqbot-qwenpaw/requirements.lock
COPY dsh-launch.py dsh-acp.patch.yml acp.example.json bootstrap.py compat.py /opt/qqbot-qwenpaw/
RUN /opt/qwenpaw-venv/bin/python /opt/qqbot-qwenpaw/compat.py
COPY qqbot-plugin /opt/qqbot-qwenpaw/qqbot-plugin
ENV PATH=/opt/qwenpaw-venv/bin:$PATH \
    QWENPAW_WORKING_DIR=/state/qwenpaw QWENPAW_WORKDIR=/state/qwenpaw \
    QWENPAW_TELEMETRY_DISABLED=true HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
USER agent
WORKDIR /state
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/api/healthz',timeout=3)"
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["qwenpaw", "app", "--host", "127.0.0.1", "--port", "8088", "--log-level", "warning"]
