# Build once before accepting product uploads; runtime never installs or compiles source.
ARG HARNESS_BASE_IMAGE
FROM ${HARNESS_BASE_IMAGE} AS dependencies
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/harness
COPY deploy/product-ingestion/requirements.lock /opt/runtime-requirements.lock
RUN --mount=type=cache,id=g3-harness-pip-v1,target=/root/.cache/pip \
    pip install --require-hashes -r /opt/runtime-requirements.lock
FROM dependencies AS runtime
COPY harness/src ./src
COPY harness/migrations ./migrations
COPY harness/alembic.ini ./alembic.ini
ENV PYTHONPATH=/opt/harness/src
USER 10001:10001
CMD ["python", "-c", "from insurance_harness.service_shell.cli import api_main; api_main()"]
