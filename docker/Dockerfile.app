# syntax=docker/dockerfile:1.7

ARG BUILDER_IMAGE
ARG RUNTIME_IMAGE

FROM ${BUILDER_IMAGE} AS builder

WORKDIR /app

# Python is the only bootstrap dependency needed to turn the copied, validated
# lock into shell data. Its source, Release files, and package version are still
# passed from the same lock by the selector and verified before apt installs it.
ARG DEBIAN_SNAPSHOT_BOOTSTRAP
ARG DEBIAN_SECURITY_SNAPSHOT_BOOTSTRAP
ARG DEBIAN_RELEASE_SHA256_BOOTSTRAP
ARG DEBIAN_SECURITY_RELEASE_SHA256_BOOTSTRAP
ARG PYTHON3_VERSION_BOOTSTRAP
RUN printf 'deb [check-valid-until=no] %s bookworm main\ndeb [check-valid-until=no] %s bookworm-security main\n' "$DEBIAN_SNAPSHOT_BOOTSTRAP" "$DEBIAN_SECURITY_SNAPSHOT_BOOTSTRAP" > /etc/apt/sources.list && \
    rm -f /etc/apt/sources.list.d/debian.sources && \
    curl -fsSL "${DEBIAN_SNAPSHOT_BOOTSTRAP}dists/bookworm/Release" -o /tmp/debian-Release && \
    printf '%s  %s\n' "$DEBIAN_RELEASE_SHA256_BOOTSTRAP" /tmp/debian-Release | sha256sum -c - && \
    curl -fsSL "${DEBIAN_SECURITY_SNAPSHOT_BOOTSTRAP}dists/bookworm-security/Release" -o /tmp/debian-security-Release && \
    printf '%s  %s\n' "$DEBIAN_SECURITY_RELEASE_SHA256_BOOTSTRAP" /tmp/debian-security-Release | sha256sum -c - && \
    apt-get update && \
    apt-get install -y --no-install-recommends "python3=$PYTHON3_VERSION_BOOTSTRAP"

COPY deploy/local-build/app-external-dependencies.v1.json /tmp/app-external-dependencies.v1.json
COPY scripts/app_artifact.py scripts/app_artifact.py
RUN python3 scripts/app_artifact.py dependency-plan --lock /tmp/app-external-dependencies.v1.json --output /tmp/ba0-dependency-plan.env

RUN . /tmp/ba0-dependency-plan.env && \
    test "$BA0_SCHEMA_VERSION" = "1" && \
    test "$BA0_PLATFORM_OS" = "linux" && \
    test "$BA0_PLATFORM_ARCH" = "arm64"

# Reconfigure from the exact parser output. Bootstrap values are deliberately
# not trusted as the installation dataflow after the plan exists.
RUN . /tmp/ba0-dependency-plan.env && \
    printf 'deb [check-valid-until=no] %s bookworm main\ndeb [check-valid-until=no] %s bookworm-security main\n' "$BA0_DEBIAN_REPOSITORIES_DEBIAN_SNAPSHOT" "$BA0_DEBIAN_REPOSITORIES_DEBIAN_SECURITY_SNAPSHOT" > /etc/apt/sources.list && \
    curl -fsSL "${BA0_DEBIAN_REPOSITORIES_DEBIAN_SNAPSHOT}dists/bookworm/Release" -o /tmp/debian-Release && \
    printf '%s  %s\n' "$BA0_DEBIAN_REPOSITORIES_DEBIAN_RELEASE_SHA256" /tmp/debian-Release | sha256sum -c - && \
    curl -fsSL "${BA0_DEBIAN_REPOSITORIES_DEBIAN_SECURITY_SNAPSHOT}dists/bookworm-security/Release" -o /tmp/debian-security-Release && \
    printf '%s  %s\n' "$BA0_DEBIAN_REPOSITORIES_DEBIAN_SECURITY_RELEASE_SHA256" /tmp/debian-security-Release | sha256sum -c - && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        "git=$BA0_DEBIAN_PACKAGES_GIT" \
        "build-essential=$BA0_DEBIAN_PACKAGES_BUILD_ESSENTIAL" \
        "libsqlite3-dev=$BA0_DEBIAN_PACKAGES_LIBSQLITE3_DEV" && \
    rm -rf /var/lib/apt/lists/*

COPY go.mod go.sum ./
RUN --mount=type=cache,id=ba0-app-go-mod-v1,target=/go/pkg/mod,sharing=locked \
    --mount=type=cache,id=ba0-app-go-build-v1,target=/root/.cache/go-build,sharing=locked \
    go mod download

RUN --mount=type=cache,id=ba0-app-go-mod-v1,target=/go/pkg/mod,sharing=locked \
    --mount=type=cache,id=ba0-app-go-build-v1,target=/root/.cache/go-build,sharing=locked \
    . /tmp/ba0-dependency-plan.env && \
    grep -F "$BA0_DOWNLOADS_GO_TOOLS_MIGRATE_GO_SUM" go.sum && \
    go install -tags postgres "${BA0_DOWNLOADS_GO_TOOLS_MIGRATE_MODULE}@${BA0_DOWNLOADS_GO_TOOLS_MIGRATE_VERSION}"

COPY cmd/download cmd/download
RUN --mount=type=cache,id=ba0-app-go-mod-v1,target=/go/pkg/mod,sharing=locked \
    --mount=type=cache,id=ba0-app-go-build-v1,target=/root/.cache/go-build,sharing=locked \
    . /tmp/ba0-dependency-plan.env && \
    go run cmd/download/duckdb/duckdb.go \
        --lock /tmp/app-external-dependencies.v1.json \
        --goos "$BA0_PLATFORM_OS" \
        --goarch "$BA0_PLATFORM_ARCH" \
        --duckdb-platform "$BA0_PLATFORM_DUCKDB" \
        --duckdb-version "$BA0_DOWNLOADS_DUCKDB_VERSION" \
        --spatial-origin "$BA0_DOWNLOADS_DUCKDB_EXTENSIONS_SPATIAL_ORIGIN" \
        --spatial-sha256 "$BA0_DOWNLOADS_DUCKDB_EXTENSIONS_SPATIAL_SHA256" \
        --excel-origin "$BA0_DOWNLOADS_DUCKDB_EXTENSIONS_EXCEL_ORIGIN" \
        --excel-sha256 "$BA0_DOWNLOADS_DUCKDB_EXTENSIONS_EXCEL_SHA256" \
        --spatial-platform "$BA0_DOWNLOADS_DUCKDB_EXTENSIONS_SPATIAL_PLATFORM" \
        --excel-platform "$BA0_DOWNLOADS_DUCKDB_EXTENSIONS_EXCEL_PLATFORM" && \
    printf 'ba0-app-go-mod-cache-v1\n' > /go/pkg/mod/.ba0-app-cache-v1 && \
    test -s /go/pkg/mod/.ba0-app-cache-v1 && \
    printf 'ba0-app-go-build-cache-v1\n' > /root/.cache/go-build/.ba0-app-cache-v1 && \
    test -s /root/.cache/go-build/.ba0-app-cache-v1

COPY . .

ARG VERSION_ARG
ARG COMMIT_ID_ARG
ARG SOURCE_DATE_EPOCH
ENV VERSION=${VERSION_ARG}
ENV COMMIT_ID=${COMMIT_ID_ARG}
RUN --mount=type=cache,id=ba0-app-go-mod-v1,target=/go/pkg/mod,sharing=locked \
    --mount=type=cache,id=ba0-app-go-build-v1,target=/root/.cache/go-build,sharing=locked \
    test -s /go/pkg/mod/.ba0-app-cache-v1 && \
    test -s /root/.cache/go-build/.ba0-app-cache-v1 && \
    test -n "$VERSION" && \
    test -n "$COMMIT_ID" && \
    test -n "$SOURCE_DATE_EPOCH" && \
    GO_VERSION="$(go version)" && \
    BUILD_TIME="$(date -u -d "@$SOURCE_DATE_EPOCH" '+%Y-%m-%d %H:%M:%S UTC')" && \
    VERSION="$VERSION" COMMIT_ID="$COMMIT_ID" BUILD_TIME="$BUILD_TIME" GO_VERSION="$GO_VERSION" make build-prod

RUN --mount=type=cache,id=ba0-app-go-mod-v1,target=/go/pkg/mod,sharing=locked \
    mkdir -p /app/yanyiwu && \
    cp -R /go/pkg/mod/github.com/yanyiwu/. /app/yanyiwu/


FROM ${RUNTIME_IMAGE} AS runtime

WORKDIR /app

COPY --from=builder /tmp/ba0-dependency-plan.env /tmp/ba0-dependency-plan.env
COPY --from=builder /tmp/debian-Release /tmp/debian-Release
COPY --from=builder /tmp/debian-security-Release /tmp/debian-security-Release
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt

# The pinned builder supplies only the TLS trust anchor and the Release files it
# already verified. Re-verify those files from the runtime lock plan before the
# first apt network operation, then install the complete pinned runtime set.
RUN . /tmp/ba0-dependency-plan.env && \
    printf 'deb [check-valid-until=no] %s bookworm main\ndeb [check-valid-until=no] %s bookworm-security main\n' "$BA0_DEBIAN_REPOSITORIES_DEBIAN_SNAPSHOT" "$BA0_DEBIAN_REPOSITORIES_DEBIAN_SECURITY_SNAPSHOT" > /etc/apt/sources.list && \
    rm -f /etc/apt/sources.list.d/debian.sources && \
    printf '%s  %s\n' "$BA0_DEBIAN_REPOSITORIES_DEBIAN_RELEASE_SHA256" /tmp/debian-Release | sha256sum -c - && \
    printf '%s  %s\n' "$BA0_DEBIAN_REPOSITORIES_DEBIAN_SECURITY_RELEASE_SHA256" /tmp/debian-security-Release | sha256sum -c - && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        "git=$BA0_DEBIAN_PACKAGES_GIT" \
        "build-essential=$BA0_DEBIAN_PACKAGES_BUILD_ESSENTIAL" \
        "libsqlite3-dev=$BA0_DEBIAN_PACKAGES_LIBSQLITE3_DEV" \
        "ca-certificates=$BA0_DEBIAN_PACKAGES_CA_CERTIFICATES" \
        "postgresql-client=$BA0_DEBIAN_PACKAGES_POSTGRESQL_CLIENT" \
        "default-mysql-client=$BA0_DEBIAN_PACKAGES_DEFAULT_MYSQL_CLIENT" \
        "tzdata=$BA0_DEBIAN_PACKAGES_TZDATA" \
        "sed=$BA0_DEBIAN_PACKAGES_SED" \
        "curl=$BA0_DEBIAN_PACKAGES_CURL" \
        "bash=$BA0_DEBIAN_PACKAGES_BASH" \
        "vim=$BA0_DEBIAN_PACKAGES_VIM" \
        "wget=$BA0_DEBIAN_PACKAGES_WGET" \
        "libsqlite3-0=$BA0_DEBIAN_PACKAGES_LIBSQLITE3_0" \
        "python3=$BA0_DEBIAN_PACKAGES_PYTHON3" \
        "python3-pip=$BA0_DEBIAN_PACKAGES_PYTHON3_PIP" \
        "python3-dev=$BA0_DEBIAN_PACKAGES_PYTHON3_DEV" \
        "libffi-dev=$BA0_DEBIAN_PACKAGES_LIBFFI_DEV" \
        "libssl-dev=$BA0_DEBIAN_PACKAGES_LIBSSL_DEV" \
        "nodejs=$BA0_DEBIAN_PACKAGES_NODEJS" \
        "npm=$BA0_DEBIAN_PACKAGES_NPM" \
        "gosu=$BA0_DEBIAN_PACKAGES_GOSU" \
        "ffmpeg=$BA0_DEBIAN_PACKAGES_FFMPEG"

RUN useradd -m -s /bin/bash appuser

RUN . /tmp/ba0-dependency-plan.env && \
    curl -fsSL "$BA0_PYTHON_TOOLS_PIP_ORIGIN" -o "/tmp/pip-$BA0_PYTHON_TOOLS_PIP_VERSION.whl" && \
    printf '%s  %s\n' "$BA0_PYTHON_TOOLS_PIP_SHA256" "/tmp/pip-$BA0_PYTHON_TOOLS_PIP_VERSION.whl" | sha256sum -c - && \
    curl -fsSL "$BA0_PYTHON_TOOLS_SETUPTOOLS_ORIGIN" -o "/tmp/setuptools-$BA0_PYTHON_TOOLS_SETUPTOOLS_VERSION.whl" && \
    printf '%s  %s\n' "$BA0_PYTHON_TOOLS_SETUPTOOLS_SHA256" "/tmp/setuptools-$BA0_PYTHON_TOOLS_SETUPTOOLS_VERSION.whl" | sha256sum -c - && \
    curl -fsSL "$BA0_PYTHON_TOOLS_WHEEL_ORIGIN" -o "/tmp/wheel-$BA0_PYTHON_TOOLS_WHEEL_VERSION.whl" && \
    printf '%s  %s\n' "$BA0_PYTHON_TOOLS_WHEEL_SHA256" "/tmp/wheel-$BA0_PYTHON_TOOLS_WHEEL_VERSION.whl" | sha256sum -c - && \
    curl -fsSL "$BA0_PYTHON_TOOLS_PACKAGING_ORIGIN" -o "/tmp/packaging-$BA0_PYTHON_TOOLS_PACKAGING_VERSION.whl" && \
    printf '%s  %s\n' "$BA0_PYTHON_TOOLS_PACKAGING_SHA256" "/tmp/packaging-$BA0_PYTHON_TOOLS_PACKAGING_VERSION.whl" | sha256sum -c - && \
    pip3 install --break-system-packages --no-index \
        "/tmp/pip-$BA0_PYTHON_TOOLS_PIP_VERSION.whl" \
        "/tmp/setuptools-$BA0_PYTHON_TOOLS_SETUPTOOLS_VERSION.whl" \
        "/tmp/wheel-$BA0_PYTHON_TOOLS_WHEEL_VERSION.whl" \
        "/tmp/packaging-$BA0_PYTHON_TOOLS_PACKAGING_VERSION.whl"

RUN . /tmp/ba0-dependency-plan.env && \
    curl -fsSL "$BA0_DOWNLOADS_UV_ORIGIN" -o "/tmp/uv-$BA0_DOWNLOADS_UV_VERSION-$BA0_DOWNLOADS_UV_PLATFORM.tar.gz" && \
    printf '%s  %s\n' "$BA0_DOWNLOADS_UV_SHA256" "/tmp/uv-$BA0_DOWNLOADS_UV_VERSION-$BA0_DOWNLOADS_UV_PLATFORM.tar.gz" | sha256sum -c - && \
    mkdir -p /tmp/uv /home/appuser/.local/bin && \
    tar -xzf "/tmp/uv-$BA0_DOWNLOADS_UV_VERSION-$BA0_DOWNLOADS_UV_PLATFORM.tar.gz" -C /tmp/uv --strip-components=1 && \
    sh -eu -c 'install -m 0755 /tmp/uv/uv /home/appuser/.local/bin/uv; install -m 0755 /tmp/uv/uvx /home/appuser/.local/bin/uvx' && \
    ln -s /home/appuser/.local/bin/uvx /usr/local/bin/uvx

RUN mkdir -p /data/files /home/appuser/.local/bin && \
    chown -R appuser:appuser /app /data/files /home/appuser

COPY --from=builder /go/bin/migrate /usr/local/bin/migrate
COPY --from=builder /app/yanyiwu/ /go/pkg/mod/github.com/yanyiwu/
COPY --from=builder /app/config ./config
COPY --from=builder /app/scripts ./scripts
COPY --from=builder /app/migrations ./migrations
COPY --from=builder /app/dataset/samples ./dataset/samples
COPY --from=builder /app/skills/preloaded ./skills/preloaded
COPY --from=builder /app/skills/preloaded ./skills/_builtin
COPY --from=builder /root/.duckdb /home/appuser/.duckdb
COPY --from=builder /app/WeKnora ./WeKnora

RUN chmod +x ./scripts/*.sh && \
    chown -R appuser:appuser /app /home/appuser/.duckdb

EXPOSE 8080
ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["./WeKnora"]
