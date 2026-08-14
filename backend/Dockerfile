FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kronos (github.com/shiyu-coder/Kronos) has no setup.py/pyproject.toml -- it's
# not pip-installable, so it's cloned directly and put on PYTHONPATH instead.
# KRONOS_REPO_PATH (set in docker-compose.yml) must match this location.
RUN git clone --depth 1 https://github.com/shiyu-coder/Kronos.git /opt/kronos
ENV PYTHONPATH=/opt/kronos:$PYTHONPATH

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
