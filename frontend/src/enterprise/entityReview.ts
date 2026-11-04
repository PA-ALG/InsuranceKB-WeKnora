import type { Release, ReleaseMember } from './enterpriseApi'
import { profileMemberFor } from './releaseView'
import vocabulary from './entityReviewVocabulary.json'

type Payload = Record<string, unknown>
export interface EntityCell { present: boolean; value?: unknown; explanation?: string }
export interface EntityFieldChange { path: string; before: EntityCell; after: EntityCell }
export interface EntityReview {
  name: string; beforeKnown: boolean; fields: EntityFieldChange[]
}
const record = (value: unknown): Payload | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Payload : null
const strings = (value: unknown): string[] => Array.isArray(value)
  ? value.filter((item): item is string => typeof item === 'string' && !!item.trim()) : []
const text = (value: unknown): string => typeof value === 'string' ? value : ''
const pointer = (path: string[]) => path.map(key => `/${key.replace(/~/g, '~0').replace(/\//g, '~1')}`).join('')
const cell = (value: Payload | null, key: string): EntityCell => value && Object.hasOwn(value, key)
  ? { present: true, value: value[key] } : { present: false }

function canonical(value: unknown): string | undefined {
  return JSON.stringify(value, (_key, child: unknown) => {
    const object = record(child)
    return object ? Object.fromEntries(Object.keys(object).sort().map(key => [key, object[key]])) : child
  })
}

function diff(before: Payload | null, after: Payload | null): EntityFieldChange[] {
  const fields: EntityFieldChange[] = []
  const pending: { path: string[]; before: EntityCell; after: EntityCell }[] = [{ path: [], before: before ? { present: true, value: before } : { present: false },
    after: after ? { present: true, value: after } : { present: false } }]
  while (pending.length) {
    const node = pending.pop()!
    if (node.before.present === node.after.present && canonical(node.before.value) === canonical(node.after.value)) continue
    const old = record(node.before.value), next = record(node.after.value)
    // Existing objects recurse even when one becomes empty. A missing empty container remains a value.
    const keys = [...new Set([...Object.keys(old ?? {}), ...Object.keys(next ?? {})])].sort()
    if (keys.length && ((old && next) || (!node.before.present && next) || (!node.after.present && old))) {
      for (const key of keys.reverse()) pending.push({ path: [...node.path, key], before: cell(old, key), after: cell(next, key) })
    } else fields.push({ path: pointer(node.path), before: node.before, after: node.after })
  }
  return fields
}

function explain(cell: EntityCell, path: string, payload: Payload | null, release: Release): EntityCell {
  const source = (vocabulary.profile_dictionaries as Record<string, string>)[path]
  if (!source || !cell.present || typeof cell.value !== 'string' || !payload) return cell
  const profile = profileMemberFor(release, text(payload.entity_type), strings(payload.classification_labels))
  const dictionary = record(profile?.[source])
  const explanation = dictionary && Object.hasOwn(dictionary, cell.value) ? dictionary[cell.value] : null
  return typeof explanation === 'string' && explanation.trim() ? { ...cell, explanation } : cell
}

/** Project only the same member's paired payloads. No reads, decisions or inferred domain facts. */
export function entityReview(
  slug: string, old: ReleaseMember | undefined, next: ReleaseMember | undefined,
  beforeKnown: boolean, beforeRelease: Release, afterRelease: Release,
): EntityReview | undefined {
  const before = beforeKnown && old?.kind === 'entity' ? record(old.payload) : null
  const after = next?.kind === 'entity' ? record(next.payload) : null
  if (next && !after) return undefined
  if (!before && !after) return undefined
  const identity = after ?? before!
  const name = strings(identity.names)[0] || text(identity.entity_id).trim() || slug
  return { name, beforeKnown, fields: diff(before, after).map(field => ({ ...field,
    before: explain(field.before, field.path, before, beforeRelease),
    after: explain(field.after, field.path, after, afterRelease),
  })) }
}
