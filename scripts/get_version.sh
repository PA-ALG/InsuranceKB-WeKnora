#!/bin/bash
set -euo pipefail

# Binary metadata is anchored to the immutable build source rather than the
# integration checkout or wall clock. The Linux builder supplies GO_VERSION.
BUILD_SOURCE_HEAD="${BUILD_SOURCE_HEAD:-$(git rev-parse HEAD)}"
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git show -s --format=%ct "$BUILD_SOURCE_HEAD")}"
VERSION="$(git show "$BUILD_SOURCE_HEAD:VERSION" | tr -d '\n\r')"
EDITION="${EDITION:-standard}"
COMMIT_ID="$BUILD_SOURCE_HEAD"
GO_VERSION="${GO_VERSION:-unknown}"

if BUILD_TIME="$(date -u -r "$SOURCE_DATE_EPOCH" '+%Y-%m-%d %H:%M:%S UTC' 2>/dev/null)"; then
    :
else
    BUILD_TIME="$(date -u -d "@$SOURCE_DATE_EPOCH" '+%Y-%m-%d %H:%M:%S UTC')"
fi

case "${1:-env}" in
    env)
        echo "VERSION=$VERSION"
        echo "EDITION=$EDITION"
        echo "COMMIT_ID=$COMMIT_ID"
        echo "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH"
        echo "BUILD_TIME=\"$BUILD_TIME\""
        echo "GO_VERSION=\"$GO_VERSION\""
        ;;
    json)
        printf '{\n'
        printf '  "version": "%s",\n' "$VERSION"
        printf '  "edition": "%s",\n' "$EDITION"
        printf '  "commit_id": "%s",\n' "$COMMIT_ID"
        printf '  "source_date_epoch": %s,\n' "$SOURCE_DATE_EPOCH"
        printf '  "build_time": "%s"\n' "$BUILD_TIME"
        printf '}\n'
        ;;
    docker-args)
        echo "--build-arg VERSION_ARG=$VERSION"
        echo "--build-arg COMMIT_ID_ARG=$COMMIT_ID"
        echo "--build-arg SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH"
        ;;
    ldflags)
        echo "-X 'github.com/Tencent/WeKnora/internal/handler.Version=$VERSION' -X 'github.com/Tencent/WeKnora/internal/handler.Edition=$EDITION' -X 'github.com/Tencent/WeKnora/internal/handler.CommitID=$COMMIT_ID' -X 'github.com/Tencent/WeKnora/internal/handler.BuildTime=$BUILD_TIME' -X 'github.com/Tencent/WeKnora/internal/handler.GoVersion=$GO_VERSION' -X 'github.com/Tencent/WeKnora/internal/application/service.RevisionBuildVersion=$VERSION' -X 'github.com/Tencent/WeKnora/internal/application/service.RevisionBuildCommit=$COMMIT_ID'"
        ;;
    info)
        echo "Version: $VERSION"
        echo "Edition: $EDITION"
        echo "Commit ID: $COMMIT_ID"
        echo "Source date epoch: $SOURCE_DATE_EPOCH"
        echo "Build time: $BUILD_TIME"
        ;;
    *)
        echo "usage: $0 [env|json|docker-args|ldflags|info]" >&2
        exit 2
        ;;
esac
