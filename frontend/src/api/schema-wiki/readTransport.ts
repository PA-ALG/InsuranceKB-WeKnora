import type { SchemaWikiReadTransport } from './index'

// Fixed-release reads replay source checks before returning; keep a finite, read-only budget.
export const SCHEMA_WIKI_READ_TIMEOUT_MS = 180_000

type Read = (path: string, options: { timeout: number }) => Promise<unknown>

export function createSchemaWikiReadTransport(read: Read): SchemaWikiReadTransport {
  // One load owns this map. No responses are reused across navigation or release changes.
  const pending = new Map<string, Promise<unknown>>()
  return { get(path: string) {
    let result = pending.get(path)
    if (!result) {
      result = Promise.resolve().then(() => read(path, { timeout: SCHEMA_WIKI_READ_TIMEOUT_MS }))
      pending.set(path, result)
    }
    return result
  } }
}
