# Reviewed local Phase 3 base. Override only with another reviewed immutable digest.
ARG PYTHON_BASE_IMAGE=python@sha256:c24c34b502635f1f7c4e99dc09a2cbd85d480b7dcfd077198c6b5af138906390
ARG NODE_BASE_IMAGE=node@sha256:d272d96f3ad3a4e5bb2b6c36ea7427b4e83d1b23fb24b9df8b71d01aa59951b1
FROM ${NODE_BASE_IMAGE} AS node-runtime
FROM ${PYTHON_BASE_IMAGE}

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/rosetta/src

RUN addgroup --system --gid 65532 rosetta && \
    adduser --system --uid 65532 --ingroup rosetta --home /nonexistent --no-create-home rosetta

WORKDIR /opt/rosetta
COPY requirements.lock pyproject.toml ./
RUN python -m pip install --no-cache-dir --require-hashes --requirement requirements.lock
COPY src ./src
COPY config ./config
COPY adapters ./adapters
COPY vendor/technocore-chat-v0.10.0/mcp/src ./vendor/technocore-chat-v0.10.0/mcp/src

USER 65532:65532
ENTRYPOINT ["python", "-m"]
CMD ["rosetta.cli", "--help"]
