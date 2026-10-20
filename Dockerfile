ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY pyproject.toml requirements.lock ./
COPY qqbot ./qqbot
RUN pip install -r requirements.lock && pip install --no-deps .
COPY bot.py ./
RUN mkdir -p /app/data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["python", "-u", "bot.py"]
