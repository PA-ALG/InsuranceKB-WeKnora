import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
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
  assert.match(activeNginxConfig, /location\s*=\s*\/health\s*\{[^}]*proxy_pass\s+\$\{APP_SCHEME\}:\/\/weknora_app\/health;/)
})

test('backend startup failure has an available error response', () => {
  assert.doesNotMatch(activeNginxConfig, /error_page[^;]*\/50x\.html/)
  assert.match(activeNginxConfig, /error_page\s+500\s+502\s+503\s+504\s*=503\s+@backend_unavailable;/)
  assert.match(activeNginxConfig, /location\s+@backend_unavailable\s*\{[^}]*return\s+503\s/)
})

const entrypoint = readFileSync(new URL('../../docker-entrypoint.sh', import.meta.url), 'utf8')

test('backend DNS updates are shared without changing proxy URI suffixes', () => {
  assert.match(activeNginxConfig, /upstream\s+weknora_app\s*\{[^}]*zone\s+weknora_app\s+64k;/)
  assert.match(activeNginxConfig, /resolver\s+\$\{APP_DNS_RESOLVER\}\s+valid=5s;/)
  assert.match(activeNginxConfig, /server\s+\$\{APP_HOST\}:\$\{APP_PORT\}\s+resolve;/)
  for (const suffix of ['/api/', '/files', '/health']) {
    assert.ok(activeNginxConfig.includes('proxy_pass ${APP_SCHEME}://weknora_app' + suffix + ';'))
  }
  assert.match(entrypoint, /envsubst[^\n]*\$\{APP_DNS_RESOLVER\}/)
})

function resolver(resolvConf: string, override?: string) {
  const directory = mkdtempSync(join(tmpdir(), 'weknora-dns-'))
  try {
    const input = join(directory, 'resolv.conf')
    writeFileSync(input, resolvConf)
    const prefix = entrypoint.slice(0, entrypoint.indexOf('# Schema Wiki MVP'))
      .replaceAll('/etc/resolv.conf', '"$TEST_RESOLV_CONF"')
    const env: NodeJS.ProcessEnv = { ...process.env, TEST_RESOLV_CONF: input }
    delete env.APP_DNS_RESOLVER
    if (override !== undefined) env.APP_DNS_RESOLVER = override
    return spawnSync('/bin/sh', ['-c', prefix + '\nprintf "%s" "$APP_DNS_RESOLVER"'], { env, encoding: 'utf8' })
  } finally { rmSync(directory, { recursive: true, force: true }) }
}

test('entrypoint discovers container DNS and brackets bare IPv6 addresses', () => {
  const docker = resolver('search local\nnameserver 127.0.0.11\n')
  assert.equal(docker.status, 0); assert.equal(docker.stdout, '127.0.0.11')
  const ipv6 = resolver('nameserver 2001:db8::53\n')
  assert.equal(ipv6.status, 0); assert.equal(ipv6.stdout, '[2001:db8::53]')
})

test('explicit DNS resolver wins, including bracketed IPv6 with a port', () => {
  const result = resolver('nameserver 127.0.0.11\n', '[::1]:5353')
  assert.equal(result.status, 0); assert.equal(result.stdout, '[::1]:5353')
})

test('missing or unsafe DNS resolver fails instead of selecting public DNS', () => {
  assert.notEqual(resolver('search local\n').status, 0)
  assert.notEqual(resolver('', '127.0.0.11; include /tmp/other;').status, 0)
})
