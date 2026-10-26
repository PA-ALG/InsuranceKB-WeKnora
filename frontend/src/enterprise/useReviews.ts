import { onScopeDispose, reactive, ref, shallowRef, watch, type Ref } from 'vue'
import { decideReview, EnterpriseError, listReviews, readRelease, readReview,
  type Release, type ReviewDetail, type ReviewItem, type ReviewResult } from './enterpriseApi'
import { reviewReasonLength, trimReviewReason } from './reviewReason'
import { reviewChanges } from './reviewView'

export type ReviewTab = 'pending' | 'decided'
export interface ReviewEntry {
  item: ReviewItem; detail: ReviewDetail | null; phase: 'idle' | 'loading' | 'ready' | 'failed'
  reason: string; busy: boolean; error: string; result: ReviewResult | null; operation: number
}
export interface ReviewFocus { valid: () => boolean; target: 'tab' | 'detail' | 'state'; id: string }
const failure = (error: unknown) => error instanceof EnterpriseError ? error.code : 'REQUEST_FAILED'
export function canDecide(entry: ReviewEntry, release: Release | null, outcome: 'approve' | 'reject') {
  const count = reviewReasonLength(entry.reason)
  return !!entry.detail && entry.phase === 'ready' && !entry.busy && !entry.result
    && entry.detail.status === 'pending' && count > 0 && count <= 2000
    && (outcome === 'reject' || (!entry.detail.blocker && reviewChanges(entry.detail, release) !== null))
}
export function useReviews(spaceId: Readonly<Ref<string>>) {
  const tab = ref<ReviewTab>('pending'), state = ref<'loading' | 'failed' | 'ready'>('loading')
  const release = shallowRef<Release | null>(null), entries = ref<ReviewEntry[]>([]), notice = ref(false)
  let generation = 0
  // Every list read creates a new lifetime, including the paired Release read and every card.
  async function load(decidedElsewhere = false): Promise<ReviewFocus> {
    const version = ++generation, space = spaceId.value, status = tab.value
    const valid = () => version === generation
    entries.value = []; release.value = null; state.value = 'loading'; notice.value = decidedElsewhere
    try {
      const [items, snapshot] = await Promise.all([listReviews(space, status), readRelease(space).catch(() => null)])
      if (valid()) {
        if (!Array.isArray(items)) throw new EnterpriseError('INVALID_RESPONSE')
        release.value = snapshot
        entries.value = [...new Map(items.filter(item => status === 'pending' ? item.status === 'pending'
          : ['approved', 'rejected', 'released'].includes(item.status)).map(item => [item.candidate_id, item])).values()]
          .map(item => reactive({ item, detail: null, phase: 'idle' as const, reason: '', busy: false, error: '', result: null, operation: 0 }))
        state.value = 'ready'
      }
    } catch { if (valid()) state.value = 'failed' }
    return { valid, target: 'tab', id: '' }
  }
  function current(entry: ReviewEntry, version: number, operation: number) {
    return generation === version && entry.operation === operation && entries.value.includes(entry)
  }
  async function open(entry: ReviewEntry): Promise<ReviewFocus | null> {
    if (!entries.value.includes(entry) || entry.busy || entry.result) return null
    const version = generation, operation = ++entry.operation, space = spaceId.value
    const valid = () => current(entry, version, operation)
    entry.phase = 'loading'; entry.error = ''; entry.detail = null
    try {
      const detail = await readReview(space, entry.item.candidate_id)
      if (valid()) {
        if (!detail || detail.candidate_id !== entry.item.candidate_id || !Array.isArray(detail.bundle_members)
          || !Array.isArray(detail.bundle_removals)) throw new EnterpriseError('INVALID_RESPONSE')
        entry.detail = detail; entry.phase = 'ready'
      }
    } catch (error) { if (valid()) { entry.error = failure(error); entry.phase = 'failed' } }
    return { valid, target: 'detail', id: entry.item.candidate_id }
  }
  async function decide(entry: ReviewEntry, outcome: 'approve' | 'reject'): Promise<ReviewFocus | null> {
    if (!entries.value.includes(entry) || !canDecide(entry, release.value, outcome)) return null
    const version = generation, operation = ++entry.operation, space = spaceId.value
    const valid = () => current(entry, version, operation)
    entry.busy = true; entry.error = ''
    try {
      const result = await decideReview(space, entry.item.candidate_id, outcome, trimReviewReason(entry.reason))
      if (!valid()) return null
      if (!result?.decision_id || !(outcome === 'reject' ? result.status === 'rejected' : ['approved', 'released'].includes(result.status))
        || (result.status === 'released' && (!result.release_id || !Number.isInteger(result.epoch) || result.epoch! < 1))) {
        throw new EnterpriseError('INVALID_RESPONSE')
      }
      entry.result = result
      return { valid, target: 'state', id: entry.item.candidate_id }
    } catch (error) {
      if (!valid()) return null
      const code = failure(error)
      if (code === 'CANDIDATE_DECIDED') return await load(true)
      if (code === 'NEEDS_REBASE' || code === 'CANDIDATE_INVALID') {
        entry.busy = false
        return await open(entry)
      }
      entry.error = code
      return { valid, target: 'detail', id: entry.item.candidate_id }
    } finally { if (valid()) entry.busy = false }
  }
  function selectTab(next: ReviewTab) { if (next !== tab.value) { tab.value = next; void load() } }
  watch(spaceId, () => { tab.value = 'pending'; void load() }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { generation++ })
  return { tab, state, release, entries, notice, load, open, decide, selectTab }
}
