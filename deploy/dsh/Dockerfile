ARG BOT_IMAGE=xiaoai-qqbot:identity-echo-fix
FROM docker.1ms.run/library/node:24-bookworm-slim AS node-runtime
FROM ${BOT_IMAGE}
USER root
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
ARG INSTALL_SYSTEM_PACKAGES=1
RUN if [ "$INSTALL_SYSTEM_PACKAGES" = 1 ]; then apt-get update && apt-get install -y --no-install-recommends chromium git curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*; fi
COPY wheels /wheels
RUN pip install --no-index --find-links=/wheels deepseek-harness-sdk==0.2.1rc2 && rm -rf /wheels
COPY package.json package-lock.json /opt/dsh-plugins/
RUN npm ci --prefix /opt/dsh-plugins --omit=dev --ignore-scripts
COPY server.py worker.py /opt/dsh-service/
RUN printf '#!/bin/sh\nexec /usr/bin/chromium --no-sandbox --disable-dev-shm-usage "$@"\n' > /usr/local/bin/qqbot-chromium && chmod 755 /usr/local/bin/qqbot-chromium
RUN (id agent || useradd -u 10001 -m agent) && mkdir -p /state /work/tasks && chown -R agent:agent /state /work
WORKDIR /opt/dsh-service
USER agent
ENV HOME=/home/agent PYTHONUNBUFFERED=1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "server.py"]
