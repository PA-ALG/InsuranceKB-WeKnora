# Official Debian multi-arch manifest digest resolved on 2026-07-15.
ARG RUNNER_BASE_IMAGE=debian:bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818
FROM ${RUNNER_BASE_IMAGE}

ARG RUNNER_VERSION
ARG RUNNER_ARCH
ARG RUNNER_ARCHIVE
ARG RUNNER_SHA256
ARG RUNNER_DEBIAN_MIRROR=http://deb.debian.org/debian
ARG RUNNER_DEBIAN_SECURITY_MIRROR=http://deb.debian.org/debian-security
ARG RUNNER_RELEASE_BASE=https://github.com/actions/runner/releases/download
ARG RUNNER_RELEASE_PROTO=https

RUN test -n "${RUNNER_VERSION}" \
    && test "${RUNNER_VERSION}" != "UNRESOLVED" \
    && { test "${RUNNER_ARCH}" = "arm64" || test "${RUNNER_ARCH}" = "x64"; } \
    && test "${RUNNER_ARCHIVE}" = "actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz" \
    && test -n "${RUNNER_SHA256}" \
    && test "${RUNNER_SHA256}" != "UNRESOLVED" \
    && test -n "${RUNNER_DEBIAN_MIRROR}" \
    && test -n "${RUNNER_DEBIAN_SECURITY_MIRROR}" \
    && test -n "${RUNNER_RELEASE_BASE}" \
    && { test "${RUNNER_RELEASE_PROTO}" = "https" || test "${RUNNER_RELEASE_PROTO}" = "http"; } \
    && sed --in-place \
      -e "s|URIs: http://deb.debian.org/debian-security|URIs: ${RUNNER_DEBIAN_SECURITY_MIRROR}|g" \
      -e "s|URIs: http://deb.debian.org/debian|URIs: ${RUNNER_DEBIAN_MIRROR}|g" \
      /etc/apt/sources.list.d/debian.sources \
    && grep --fixed-strings --line-regexp --quiet "URIs: ${RUNNER_DEBIAN_MIRROR}" \
      /etc/apt/sources.list.d/debian.sources \
    && grep --fixed-strings --line-regexp --quiet "URIs: ${RUNNER_DEBIAN_SECURITY_MIRROR}" \
      /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl git libicu-dev \
    && useradd --create-home --uid 10001 runner \
    && mkdir -p /home/runner/actions-runner \
    && curl --fail --location --proto "=${RUNNER_RELEASE_PROTO}" --tlsv1.2 \
      --output "/tmp/${RUNNER_ARCHIVE}" \
      "${RUNNER_RELEASE_BASE}/v${RUNNER_VERSION}/${RUNNER_ARCHIVE}" \
    && echo "${RUNNER_SHA256}  /tmp/${RUNNER_ARCHIVE}" | sha256sum -c - \
    && tar --extract --gzip --file "/tmp/${RUNNER_ARCHIVE}" \
      --directory /home/runner/actions-runner \
    && rm -f "/tmp/${RUNNER_ARCHIVE}" \
    && chown -R runner:runner /home/runner/actions-runner \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=runner:runner entrypoint.sh /home/runner/entrypoint.sh
RUN chmod 0500 /home/runner/entrypoint.sh

USER runner
WORKDIR /home/runner/actions-runner
ENTRYPOINT ["/home/runner/entrypoint.sh"]
