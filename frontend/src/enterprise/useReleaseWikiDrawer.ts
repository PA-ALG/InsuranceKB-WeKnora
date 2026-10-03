import { onScopeDispose, ref, watch } from 'vue'
import { getReleaseWikiPage, getWikiPage, type WikiReleaseAuthority } from '@/api/wiki'

type ToolEvent = { tool_data?: { found_kbs?: Record<string, unknown>; release_authorities?: unknown } }
const OLD_RELEASE_MESSAGE = '该引用来自旧版本，请重新提问'

/** Release results carry their own KB identity, independent of the current UI route. */
export function resolveReleaseCitationKb(events: readonly ToolEvent[], slug: string): string {
  for (const event of [...events].reverse()) {
    const data = event.tool_data
    const found = data?.found_kbs?.[slug]
    const ids = typeof found === 'string' ? [found] : Array.isArray(found) ? found : []
    const id = ids.find(id => typeof id === 'string' && id)
    if (!id) continue
    if (!Array.isArray(data?.release_authorities)) return data?.release_authorities === undefined ? '' : id
    return data.release_authorities.some(pin => pin?.wiki_kb_id === id) ? id : ''
  }
  return ''
}

/** Use the citation-producing event first; never replace its pin with a newer Head. */
export function resolveWikiReleaseAuthority(events: readonly ToolEvent[], kbId: string, slug: string): WikiReleaseAuthority | null {
  const recent = [...events].reverse()
  const relevant = recent.filter(event => {
    const found = event.tool_data?.found_kbs?.[slug]
    return found === kbId || (Array.isArray(found) && found.includes(kbId))
  })
  for (const event of relevant.length ? relevant.slice(0, 1) : recent) {
    const authorities = event.tool_data?.release_authorities
    if (!Array.isArray(authorities)) {
      if (authorities !== undefined && relevant.includes(event)) throw new Error(OLD_RELEASE_MESSAGE)
      continue
    }
    const authority = authorities.find(value => value?.wiki_kb_id === kbId)
    if (!authority) continue
    for (const key of ['wiki_kb_id', 'space_id', 'raw_kb_id', 'release_id']) {
      if (typeof authority[key] !== 'string' || !authority[key].trim()) throw new Error(OLD_RELEASE_MESSAGE)
    }
    return { wiki_kb_id: authority.wiki_kb_id, space_id: authority.space_id,
      raw_kb_id: authority.raw_kb_id, release_id: authority.release_id }
  }
  return null
}

type DrawerPage = { slug: string; title: string; content: string; page_type: string; version: string | number }
export function useReleaseWikiDrawer() {
  const visible = ref(false)
  const page = ref<DrawerPage | null>(null)
  const authority = ref<WikiReleaseAuthority | null>(null)
  const kbId = ref('')
  const slug = ref('')
  const loading = ref(false)
  const error = ref('')
  let generation = 0
  async function open(id: string, logicalSlug: string, pin: WikiReleaseAuthority | null = null) {
    if (!id || !logicalSlug) return
    const request = ++generation
    kbId.value = id; slug.value = logicalSlug; authority.value = pin ? { ...pin } : null
    page.value = null; error.value = ''; loading.value = true; visible.value = true
    try {
      const res = pin ? await getReleaseWikiPage(pin, logicalSlug) : await getWikiPage(id, logicalSlug)
      if (request !== generation) return
      const data = res.data || res
      page.value = pin
        ? { slug: data.logical_slug, title: data.title, content: data.content, page_type: data.kind, version: pin.release_id }
        : data
    } catch (cause: any) {
      if (request !== generation) return
      const status = cause?.$httpStatus ?? cause?.status ?? cause?.response?.status
      error.value = pin && (status === 404 || status === 409) ? OLD_RELEASE_MESSAGE : '引用内容加载失败，请重试'
    } finally {
      if (request === generation) loading.value = false
    }
  }
  function follow(logicalSlug: string) { return open(kbId.value, logicalSlug, authority.value) }
  function retry() { return follow(slug.value) }
  watch(visible, value => { if (!value) { generation++; loading.value = false; page.value = null } }, { flush: 'sync' })
  onScopeDispose(() => { generation++ })
  return { visible, page, authority, kbId, loading, error, open, follow, retry }
}
