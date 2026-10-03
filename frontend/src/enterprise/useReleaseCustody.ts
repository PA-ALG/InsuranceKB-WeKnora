import { computed, onScopeDispose, ref, watch, type Ref } from 'vue'
import { get } from '@/utils/request'

/** Native reads stay disabled until classification of the current KB succeeds. */
export function useReleaseCustody(kbId: Readonly<Ref<string>>, activeTab: Ref<string>) {
  const managed = ref<boolean | null>(null)
  const loading = ref(false)
  const error = ref('')
  let generation = 0
  async function retry() {
    const request = ++generation
    const id = kbId.value
    managed.value = null
    error.value = ''
    loading.value = !!id
    if (!id) return
    try {
      const data = await get<unknown>(`/api/v1/knowledgebase/${encodeURIComponent(id)}/release-custody`)
      if (request !== generation) return
      if (!data || typeof data !== 'object' || !('managed' in data) || typeof data.managed !== 'boolean') {
        throw new Error('Invalid custody response')
      }
      managed.value = data.managed
    } catch {
      if (request === generation) error.value = '无法确认知识库发布状态，请重试'
    } finally {
      if (request === generation) loading.value = false
    }
  }
  watch([managed, activeTab], ([isManaged, tab]) => {
    if (isManaged && (tab === 'materials' || tab === 'graph')) activeTab.value = 'schema'
  }, { flush: 'sync' })
  watch(kbId, retry, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { generation++ })
  return {
    isManaged: computed(() => managed.value === true),
    nativeWikiAllowed: computed(() => managed.value === false), loading, error, retry,
  }
}
