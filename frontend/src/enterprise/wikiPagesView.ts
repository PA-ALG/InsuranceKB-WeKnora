import type { Release, ReleaseMember } from './enterpriseApi'

export interface WikiPageEntry {
  key: string
  pageType: 'concept' | 'entity'
  title: string
  slug: string
}
export interface WikiPageView extends WikiPageEntry {
  summary: string
  aliases: string[]
  content: string
  evidence: { index: number; quote: string; page: number }[]
}

function entry(member: ReleaseMember, entityId: string): WikiPageEntry | null {
  const payload = member.payload
  if (member.kind !== 'wiki_page' || member.access_scope !== 'space' || !payload ||
    !Array.isArray(payload.entity_refs) || !payload.entity_refs.includes(entityId) ||
    !member.logical_slug.startsWith(`wiki/${entityId}/`)) return null
  const key = payload.page_key
  if (typeof key !== 'string') return null
  const parts = key.split('/'), pageType = parts[0], name = parts[1]
  if (parts.length !== 2 || (pageType !== 'concept' && pageType !== 'entity') ||
    !name || name !== name.trim() || name === '.' || name === '..' ||
    payload.page_type !== pageType || member.logical_slug !== `wiki/${entityId}/${key}` ||
    typeof payload.title !== 'string') return null
  return { key, pageType, title: payload.title, slug: member.logical_slug }
}

export function wikiPages(release: Release, entityId: string): WikiPageEntry[] {
  return release.members.flatMap(member => {
    const page = entry(member, entityId)
    return page ? [page] : []
  }).sort((a, b) => (a.pageType === b.pageType ? a.title.localeCompare(b.title, 'zh') : a.pageType === 'concept' ? -1 : 1))
}

export function wikiPageView(release: Release, entityId: string, pageKey: string): WikiPageView | null {
  for (const member of release.members) {
    const page = entry(member, entityId)
    if (!page || page.key !== pageKey) continue
    const payload = member.payload
    return {
      ...page,
      summary: typeof payload.summary === 'string' ? payload.summary : '',
      aliases: Array.isArray(payload.aliases) ? payload.aliases.filter((alias): alias is string => typeof alias === 'string') : [],
      content: typeof payload.content === 'string' ? payload.content : '',
      evidence: (Array.isArray(payload.evidence) ? payload.evidence : []).flatMap((raw, index) => {
        const page = raw?.locator?.page
        // Preserve the member's original evidence index even when a malformed locator is omitted.
        return typeof raw?.quote === 'string' && Number.isInteger(page) && page > 0 ? [{ index, quote: raw.quote, page }] : []
      }),
    }
  }
  return null
}
