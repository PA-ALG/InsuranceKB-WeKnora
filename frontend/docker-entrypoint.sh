#!/bin/sh

# Use the container's own DNS for backend address changes; never add a public fallback.
app_dns_resolver=${APP_DNS_RESOLVER:-}
if [ -z "$app_dns_resolver" ]; then
  app_dns_resolver=$(awk '$1 == "nameserver" { print $2; exit }' /etc/resolv.conf)
fi
case "$app_dns_resolver" in
  ''|*[!0-9A-Fa-f.:\[\]]*)
    echo "A valid APP_DNS_RESOLVER or resolv.conf nameserver is required" >&2
    exit 1
    ;;
esac
case "$app_dns_resolver" in
  \[*\]) ;;          # Already bracketed IPv6.
  \[*\]:*) ;;        # Bracketed IPv6 with an explicit DNS port.
  *:*:*) app_dns_resolver="[$app_dns_resolver]" ;;
esac
export APP_DNS_RESOLVER="$app_dns_resolver"

# Only emit whitelisted locale tags to avoid config.js injection from env values.
RUNTIME_DEFAULT_LOCALE=""
case "${DEFAULT_LOCALE:-}" in
  zh-CN|en-US|ru-RU|ko-KR|ja-JP) RUNTIME_DEFAULT_LOCALE="${DEFAULT_LOCALE}" ;;
esac

# Schema Wiki MVP IDs are route selectors. Invalid values become inert before
# they are written into executable config.js.
schema_wiki_mvp_entry_kb_id=${SCHEMA_WIKI_MVP_ENTRY_KB_ID:-}
schema_wiki_mvp_serving_kb_id=${SCHEMA_WIKI_MVP_SERVING_KB_ID:-}
case "$schema_wiki_mvp_entry_kb_id" in
  *[!A-Za-z0-9._:-]*) schema_wiki_mvp_entry_kb_id= ;;
esac
case "$schema_wiki_mvp_serving_kb_id" in
  *[!A-Za-z0-9._:-]*) schema_wiki_mvp_serving_kb_id= ;;
esac

# 生成运行时配置文件，注入环境变量到前端
FILE_MB=${MAX_FILE_SIZE_MB:-50}
SKILL_MB=${MAX_SKILL_BUNDLE_SIZE_MB:-256}
if [ "$SKILL_MB" -lt "$FILE_MB" ] 2>/dev/null; then
  SKILL_MB=$FILE_MB
fi
if [ "$SKILL_MB" -gt 512 ] 2>/dev/null; then
  SKILL_MB=512
fi

cat > /usr/share/nginx/html/config.js << EOF
window.__RUNTIME_CONFIG__ = {
  MAX_FILE_SIZE_MB: ${FILE_MB},
  MAX_SKILL_BUNDLE_SIZE_MB: ${SKILL_MB},
  DEFAULT_LOCALE: "${RUNTIME_DEFAULT_LOCALE}",
  SCHEMA_WIKI_MVP_ENTRY_KB_ID: '${schema_wiki_mvp_entry_kb_id}',
  SCHEMA_WIKI_MVP_SERVING_KB_ID: '${schema_wiki_mvp_serving_kb_id}',
  SCHEMA_WIKI_MVP_LABEL: '当前 MVP · 只读'
};
EOF

# 处理 nginx 配置。
# 两个上限分开注入：全站保持知识库的 MAX_FILE_SIZE，只有技能 zip 上传的两条
# 集合路由放宽到 MAX_SKILL_BUNDLE_SIZE（不含 /install、PATCH 等子路径）。
# 合成一个全站上限会让每个上传端点都能收到技能包那么大的 body。
export MAX_FILE_SIZE=${FILE_MB}M
export MAX_SKILL_BUNDLE_SIZE=${SKILL_MB}M
export APP_HOST=${APP_HOST:-app}
export APP_PORT=${APP_PORT:-8080}
export APP_SCHEME=${APP_SCHEME:-http}
envsubst '${MAX_FILE_SIZE} ${MAX_SKILL_BUNDLE_SIZE} ${APP_HOST} ${APP_PORT} ${APP_SCHEME} ${APP_DNS_RESOLVER}' \
  < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

# 启动 nginx
exec nginx -g 'daemon off;'
