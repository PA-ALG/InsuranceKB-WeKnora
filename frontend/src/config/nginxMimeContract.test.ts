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
