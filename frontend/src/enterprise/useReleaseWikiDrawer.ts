import { onScopeDispose, ref, watch } from 'vue'
import { getWikiPage, type WikiPage } from '@/api/wiki'

type ToolEvent = { tool_data?: { found_kbs?: Record<string, unknown>; release_authorities?: unknown } }

/**
 * Citations from the retired 830 wiki tools carry the release they were read from
 * (`release_authorities`). That release read path is gone (S7d-2c-3c) and the current page is not
 * the cited one, so such a citation must not open at all (blueprint boundary 7). The latest event
 * that found the slug decides; with none, any pinned result in the session refuses the citation.
 */
export function citesPinnedRelease(events: readonly ToolEvent[], slug: string): boolean {
  const recent = [...events].reverse()
  const found = recent.find(event => {
    const kbs = event.tool_data?.found_kbs
    return !!kbs && Object.prototype.hasOwnProperty.call(kbs, slug)
  })
  const pinned = (event: ToolEvent) => event.tool_data?.release_authorities !== undefined
  return found ? pinned(found) : recent.some(pinned)
}

export function useReleaseWikiDrawer() {
  const visible = ref(false)
  const page = ref<WikiPage | null>(null)
  const kbId = ref('')
  const slug = ref('')
  const loading = ref(false)
  const error = ref('')
  let generation = 0
  async function open(id: string, logicalSlug: string) {
    if (!id || !logicalSlug) return
    const request = ++generation
    kbId.value = id; slug.value = logicalSlug
    page.value = null; error.value = ''; loading.value = true; visible.value = true
    try {
      const res: any = await getWikiPage(id, logicalSlug)
      if (request !== generation) return
      page.value = res.data || res
    } catch {
      if (request !== generation) return
      error.value = '引用内容加载失败，请重试'
    } finally {
      if (request === generation) loading.value = false
    }
  }
  function follow(logicalSlug: string) { return open(kbId.value, logicalSlug) }
  function retry() { return follow(slug.value) }
  watch(visible, value => { if (!value) { generation++; loading.value = false; page.value = null } }, { flush: 'sync' })
  onScopeDispose(() => { generation++ })
  return { visible, page, kbId, loading, error, open, follow, retry }
}
