FROM python:3.12-slim AS base

WORKDIR /app

RUN pip install --no-cache-dir uv

# Install SDK from packages/sdk (editable for now, PyPI in prod later)
COPY packages/sdk /app/packages/sdk
RUN cd /app/packages/sdk && uv pip install --system ".[server]"

# Install cloud API
COPY apps/api /app/apps/api
RUN cd /app/apps/api && uv pip install --system .

EXPOSE 8080

CMD ["uvicorn", "harnessbox_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
