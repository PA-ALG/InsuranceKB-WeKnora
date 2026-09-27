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

# Schema Wiki MVP KB identifiers are data selectors, so accept only route-safe IDs before
# placing them in executable config.js. Invalid or half-configured pairs become inert.
schema_wiki_mvp_entry_kb_id=${SCHEMA_WIKI_MVP_ENTRY_KB_ID:-}
schema_wiki_mvp_serving_kb_id=${SCHEMA_WIKI_MVP_SERVING_KB_ID:-}
case "$schema_wiki_mvp_entry_kb_id" in
  *[!A-Za-z0-9._:-]*) schema_wiki_mvp_entry_kb_id= ;;
esac
case "$schema_wiki_mvp_serving_kb_id" in
  *[!A-Za-z0-9._:-]*) schema_wiki_mvp_serving_kb_id= ;;
esac

# 生成运行时配置文件，注入环境变量到前端
cat > /usr/share/nginx/html/config.js << EOF
window.__RUNTIME_CONFIG__ = {
  MAX_FILE_SIZE_MB: ${MAX_FILE_SIZE_MB:-50},
  SCHEMA_WIKI_MVP_ENTRY_KB_ID: '${schema_wiki_mvp_entry_kb_id}',
  SCHEMA_WIKI_MVP_SERVING_KB_ID: '${schema_wiki_mvp_serving_kb_id}',
  SCHEMA_WIKI_MVP_LABEL: '当前 MVP · 只读'
};
EOF

# 处理 nginx 配置
export MAX_FILE_SIZE=${MAX_FILE_SIZE_MB}M
export APP_HOST=${APP_HOST:-app}
export APP_PORT=${APP_PORT:-8080}
export APP_SCHEME=${APP_SCHEME:-http}
envsubst '${MAX_FILE_SIZE} ${APP_HOST} ${APP_PORT} ${APP_SCHEME} ${APP_DNS_RESOLVER}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

# 启动 nginx
exec nginx -g 'daemon off;'
