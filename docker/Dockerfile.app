# syntax=docker/dockerfile:1.7

ARG BUILDER_IMAGE
ARG BROWSERSKILL_IMAGE
ARG RUST_IMAGE
ARG RUNTIME_IMAGE
ARG EXISTING_APP_RUNTIME=${RUNTIME_IMAGE}
ARG BROWSERSKILL_VERSION

FROM ${BUILDER_IMAGE} AS lock-plan

WORKDIR /app

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


FROM ${RUST_IMAGE} AS rust-toolchain


FROM ${RUST_IMAGE} AS anydoc-builder

WORKDIR /app
COPY --from=lock-plan /tmp/ba0-dependency-plan.env /tmp/ba0-dependency-plan.env
COPY scripts/build-anydoc-lib.sh scripts/build-anydoc-lib.sh
COPY third_party/anydoc-go third_party/anydoc-go
RUN --mount=type=cache,id=ba0-app-anydoc-cargo-registry-v1,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,id=ba0-app-anydoc-cargo-git-v1,target=/usr/local/cargo/git,sharing=locked \
    --mount=type=cache,id=ba0-app-anydoc-target-v1,target=/app/third_party/anydoc-go/target,sharing=locked \
    . /tmp/ba0-dependency-plan.env && \
    env \
        ANYDOC_CRATE_VERSION="$BA0_DOWNLOADS_ANYDOC_VERSION" \
        ANYDOC_CRATE_PLATFORM="$BA0_DOWNLOADS_ANYDOC_PLATFORM" \
        ANYDOC_CRATE_ORIGIN="$BA0_DOWNLOADS_ANYDOC_ORIGIN" \
        ANYDOC_CRATE_SHA256="$BA0_DOWNLOADS_ANYDOC_SHA256" \
        RUSTUP_TOOLCHAIN="$BA0_TOOLCHAINS_RUST" \
        bash scripts/build-anydoc-lib.sh


FROM --platform=$TARGETPLATFORM ${BROWSERSKILL_IMAGE} AS browserskill

WORKDIR /build
COPY --from=lock-plan /tmp/ba0-dependency-plan.env /tmp/ba0-dependency-plan.env
COPY --from=lock-plan /tmp/debian-Release /tmp/debian-Release
COPY --from=lock-plan /tmp/debian-security-Release /tmp/debian-security-Release
COPY --from=lock-plan /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY scripts/build_browserskill.sh scripts/browserskill-release.json ./scripts/
RUN . /tmp/ba0-dependency-plan.env && \
    printf 'deb [check-valid-until=no] %s bookworm main\ndeb [check-valid-until=no] %s bookworm-security main\n' "$BA0_DEBIAN_REPOSITORIES_DEBIAN_SNAPSHOT" "$BA0_DEBIAN_REPOSITORIES_DEBIAN_SECURITY_SNAPSHOT" > /etc/apt/sources.list && \
    rm -f /etc/apt/sources.list.d/debian.sources && \
    printf '%s  %s\n' "$BA0_DEBIAN_REPOSITORIES_DEBIAN_RELEASE_SHA256" /tmp/debian-Release | sha256sum -c - && \
    printf '%s  %s\n' "$BA0_DEBIAN_REPOSITORIES_DEBIAN_SECURITY_RELEASE_SHA256" /tmp/debian-security-Release | sha256sum -c - && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        "python3=$BA0_DEBIAN_PACKAGES_PYTHON3" \
        "ca-certificates=$BA0_DEBIAN_PACKAGES_CA_CERTIFICATES" \
        "curl=$BA0_DEBIAN_PACKAGES_CURL" \
        "build-essential=$BA0_DEBIAN_PACKAGES_BUILD_ESSENTIAL" \
        "cmake=$BA0_DEBIAN_PACKAGES_CMAKE" \
        "pkg-config=$BA0_DEBIAN_PACKAGES_PKG_CONFIG" && \
    rm -rf /var/lib/apt/lists/*
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup
COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
ARG TARGETOS
ARG TARGETARCH
RUN --mount=type=cache,id=ba0-app-browserskill-pnpm-v1,target=/root/.local/share/pnpm/store,sharing=locked \
    --mount=type=cache,id=ba0-app-browserskill-cargo-registry-v1,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,id=ba0-app-browserskill-cargo-git-v1,target=/usr/local/cargo/git,sharing=locked \
    --mount=type=cache,id=ba0-app-browserskill-target-v1,target=/var/cache/browserskill-cargo-target,sharing=locked \
    . /tmp/ba0-dependency-plan.env && \
    env \
        BROWSERSKILL_VERSION="$BA0_DOWNLOADS_BROWSERSKILL_VERSION" \
        BROWSERSKILL_SOURCE_COMMIT="$BA0_DOWNLOADS_BROWSERSKILL_SOURCE_COMMIT" \
        BROWSERSKILL_SOURCE_PLATFORM="$BA0_DOWNLOADS_BROWSERSKILL_PLATFORM" \
        BROWSERSKILL_SOURCE_ORIGIN="$BA0_DOWNLOADS_BROWSERSKILL_ORIGIN" \
        BROWSERSKILL_SOURCE_SHA256="$BA0_DOWNLOADS_BROWSERSKILL_SHA256" \
        PNPM_VERSION="$BA0_DOWNLOADS_PNPM_VERSION" \
        PNPM_PLATFORM="$BA0_DOWNLOADS_PNPM_PLATFORM" \
        PNPM_ORIGIN="$BA0_DOWNLOADS_PNPM_ORIGIN" \
        PNPM_SHA256="$BA0_DOWNLOADS_PNPM_SHA256" \
        PNPM_STORE_DIR=/root/.local/share/pnpm/store \
        CARGO_TARGET_DIR=/var/cache/browserskill-cargo-target \
        RUSTUP_TOOLCHAIN="$BA0_TOOLCHAINS_RUST" \
        bash scripts/build_browserskill.sh /opt/weknora/browserskill "${TARGETOS}/${TARGETARCH}"


FROM lock-plan AS builder

COPY go.mod go.sum ./
COPY third_party/anydoc-go/go.mod third_party/anydoc-go/go.mod
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
COPY --from=anydoc-builder /app/third_party/anydoc-go/lib/linux_arm64_gnu/libanydoc_go.a /app/third_party/anydoc-go/lib/linux_arm64_gnu/libanydoc_go.a

RUN --mount=type=cache,id=ba0-app-go-mod-v1,target=/go/pkg/mod,sharing=locked \
    --mount=type=cache,id=ba0-app-go-build-v1,target=/root/.cache/go-build,sharing=locked \
    bash ./scripts/copy-licenses.sh /license-bundle

ARG VERSION_ARG
ARG COMMIT_ID_ARG
ARG SOURCE_DATE_EPOCH
ENV VERSION=${VERSION_ARG}
ENV COMMIT_ID=${COMMIT_ID_ARG}
RUN --mount=type=cache,id=ba0-app-go-mod-v1,target=/go/pkg/mod,sharing=locked \
    --mount=type=cache,id=ba0-app-go-build-v1,target=/root/.cache/go-build,sharing=locked \
    test -n "$VERSION" && \
    test -n "$COMMIT_ID" && \
    test -n "$SOURCE_DATE_EPOCH" && \
    GO_VERSION="$(go version)" && \
    BUILD_TIME="$(date -u -d "@$SOURCE_DATE_EPOCH" '+%Y-%m-%d %H:%M:%S UTC')" && \
    VERSION="$VERSION" COMMIT_ID="$COMMIT_ID" BUILD_TIME="$BUILD_TIME" GO_VERSION="$GO_VERSION" make build-prod GO_BUILD_TAGS=anydoc && \
    go version -m /app/WeKnora | grep -F -- '-tags=anydoc'

RUN --mount=type=cache,id=ba0-app-go-mod-v1,target=/go/pkg/mod,sharing=locked \
    mkdir -p /app/yanyiwu && \
    cp -R /go/pkg/mod/github.com/yanyiwu/. /app/yanyiwu/


FROM ${EXISTING_APP_RUNTIME} AS runtime-rebase
COPY --from=builder --chown=1000:1000 /app/WeKnora /app/WeKnora
COPY --from=builder --chown=1000:1000 /app/scripts/app_artifact.py /app/scripts/app_artifact.py


FROM ${RUNTIME_IMAGE} AS runtime

WORKDIR /app

ARG BROWSERSKILL_VERSION
ENV BROWSERSKILL_BINARY=/opt/weknora/browserskill/bsk \
    BROWSERSKILL_EXTENSION_PATH=/opt/weknora/browserskill/browser-skill-weknora-${BROWSERSKILL_VERSION}.zip
COPY --from=browserskill /opt/weknora/browserskill /opt/weknora/browserskill

COPY --from=builder /tmp/ba0-dependency-plan.env /tmp/ba0-dependency-plan.env
COPY --from=builder /tmp/debian-Release /tmp/debian-Release
COPY --from=builder /tmp/debian-security-Release /tmp/debian-security-Release
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt

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
    curl -fsSL "$BA0_PYTHON_TOOLS_PIP_ORIGIN" -o "/tmp/pip-$BA0_PYTHON_TOOLS_PIP_VERSION-py3-none-any.whl" && \
    printf '%s  %s\n' "$BA0_PYTHON_TOOLS_PIP_SHA256" "/tmp/pip-$BA0_PYTHON_TOOLS_PIP_VERSION-py3-none-any.whl" | sha256sum -c - && \
    curl -fsSL "$BA0_PYTHON_TOOLS_SETUPTOOLS_ORIGIN" -o "/tmp/setuptools-$BA0_PYTHON_TOOLS_SETUPTOOLS_VERSION-py3-none-any.whl" && \
    printf '%s  %s\n' "$BA0_PYTHON_TOOLS_SETUPTOOLS_SHA256" "/tmp/setuptools-$BA0_PYTHON_TOOLS_SETUPTOOLS_VERSION-py3-none-any.whl" | sha256sum -c - && \
    curl -fsSL "$BA0_PYTHON_TOOLS_WHEEL_ORIGIN" -o "/tmp/wheel-$BA0_PYTHON_TOOLS_WHEEL_VERSION-py3-none-any.whl" && \
    printf '%s  %s\n' "$BA0_PYTHON_TOOLS_WHEEL_SHA256" "/tmp/wheel-$BA0_PYTHON_TOOLS_WHEEL_VERSION-py3-none-any.whl" | sha256sum -c - && \
    curl -fsSL "$BA0_PYTHON_TOOLS_PACKAGING_ORIGIN" -o "/tmp/packaging-$BA0_PYTHON_TOOLS_PACKAGING_VERSION-py3-none-any.whl" && \
    printf '%s  %s\n' "$BA0_PYTHON_TOOLS_PACKAGING_SHA256" "/tmp/packaging-$BA0_PYTHON_TOOLS_PACKAGING_VERSION-py3-none-any.whl" | sha256sum -c - && \
    pip3 install --break-system-packages --no-index \
        "/tmp/pip-$BA0_PYTHON_TOOLS_PIP_VERSION-py3-none-any.whl" \
        "/tmp/setuptools-$BA0_PYTHON_TOOLS_SETUPTOOLS_VERSION-py3-none-any.whl" \
        "/tmp/wheel-$BA0_PYTHON_TOOLS_WHEEL_VERSION-py3-none-any.whl" \
        "/tmp/packaging-$BA0_PYTHON_TOOLS_PACKAGING_VERSION-py3-none-any.whl"

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
COPY --from=builder /root/.duckdb /home/appuser/.duckdb
COPY --from=builder /app/WeKnora ./WeKnora
COPY --from=builder /license-bundle/ ./

RUN chmod +x ./scripts/*.sh && \
    chown -R appuser:appuser /app /home/appuser/.duckdb

EXPOSE 8080
ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["./WeKnora"]
