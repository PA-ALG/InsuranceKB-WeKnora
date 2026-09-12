import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const nginxConfig = readFileSync(new URL('../../nginx.conf', import.meta.url), 'utf8')
const activeNginxConfig = nginxConfig
  .split('\n')
  .filter((line) => !line.trimStart().startsWith('#'))
  .join('\n')

test('production nginx serves Vite module workers as JavaScript', () => {
  assert.doesNotMatch(activeNginxConfig, /location\s+\^~\s+\/assets\//)
  assert.match(
    activeNginxConfig,
    /location\s+~\*?\s+\\\.mjs\$[\s\S]*?default_type\s+application\/javascript;/,
  )
})

test('readiness reaches the backend instead of the SPA fallback', () => {
  assert.match(activeNginxConfig, /location\s*=\s*\/health\s*\{[^}]*proxy_pass\s+\$\{APP_SCHEME\}:\/\/\$\{APP_HOST\}:\$\{APP_PORT\}\/health;/)
})

test('backend startup failure has an available error response', () => {
  assert.doesNotMatch(activeNginxConfig, /error_page[^;]*\/50x\.html/)
  assert.match(activeNginxConfig, /error_page\s+500\s+502\s+503\s+504\s*=503\s+@backend_unavailable;/)
  assert.match(activeNginxConfig, /location\s+@backend_unavailable\s*\{[^}]*return\s+503\s/)
})
