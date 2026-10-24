import { onScopeDispose, ref, watch } from 'vue'
import { getWikiPage, type WikiPage } from '@/api/wiki'

type ToolData = Record<string, unknown>

const has = (value: object, key: string) => Object.prototype.hasOwnProperty.call(value, key)
const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null

/** The tool data of an event, or null when the event cannot be interpreted. */
function toolData(event: unknown): ToolData | null {
  return isObject(event) && isObject(event.tool_data) ? event.tool_data : null
}

function foundIn(data: ToolData, kbId: string, slug: string): boolean {
  const kbs = data.found_kbs
  const found = isObject(kbs) && has(kbs, slug) ? kbs[slug] : undefined
  return found === kbId || (Array.isArray(found) && found.includes(kbId))
}

/**
 * Citations from the retired 830 wiki tools carry the release they were read from
 * (`release_authorities`). That release read path is gone (S7d-2c-3c) and the current page is not
 * the cited one, so such a citation must not open at all (blueprint boundary 7).
 *
 * The decision is made for the KB the drawer is about to request: the latest event that found the
 * slug in `kbId` decides, by whether it has `release_authorities` at all. With no such event, any
 * pinned result in the session refuses the citation. Events that cannot be interpreted are skipped.
 */
export function citesPinnedRelease(events: readonly unknown[], kbId: string, slug: string): boolean {
  const data = [...events].reverse().map(toolData).filter((value): value is ToolData => value !== null)
  const pinned = (value: ToolData) => has(value, 'release_authorities')
  const producer = data.find(value => foundIn(value, kbId, slug))
  return producer ? pinned(producer) : data.some(pinned)
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
