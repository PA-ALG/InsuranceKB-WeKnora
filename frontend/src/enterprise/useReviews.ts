import { onScopeDispose, reactive, ref, shallowRef, watch, type Ref } from 'vue'
import { decidePoints, EnterpriseError, listReviews, readRelease, readReview,
  type PointResult, type Release, type ReviewDetail, type ReviewItem, type ReviewPoint } from './enterpriseApi'
import { reviewReasonLength, trimReviewReason } from './reviewReason'

export const MAX_REVIEW_POINTS = 500
export type ReviewTab = 'pending' | 'decided'
export interface PointEntry {
  point: ReviewPoint; error: string
  result: { status: 'released' | 'rejected'; epoch: number | null; reason: string } | null
}
export interface PointDecisionInput { slugs: string[]; outcome: 'approve' | 'reject'; reason: string }
export interface ReviewEntry {
  item: ReviewItem; detail: ReviewDetail | null; snapshot: Release | null; points: PointEntry[]
  phase: 'idle' | 'loading' | 'ready' | 'failed'; expanded: boolean
  busy: boolean; error: string; notice: boolean; operation: number
}
export interface ReviewFocus {
  valid: () => boolean; target: 'tab' | 'detail' | 'point-state' | 'point-error'; id: string; slug?: string
}
const failure = (error: unknown) => error instanceof EnterpriseError ? error.code : 'REQUEST_FAILED'
const statuses = ['pending', 'released', 'rejected', 'approved']
export const pendingPoint = (point: PointEntry) => point.point.status === 'pending' && !point.result
export const canCompare = (entry: ReviewEntry) => !!entry.detail && entry.detail.head_release_id === (entry.snapshot?.id ?? null)

function validItem(item: ReviewItem) {
  return item && typeof item.candidate_id === 'string' && Array.isArray(item.subjects)
    && item.subjects.every(subject => typeof subject === 'string') && statuses.includes(item.status)
    && Number.isSafeInteger(item.point_count) && Number.isSafeInteger(item.pending_points)
    && item.pending_points >= 0 && item.point_count >= item.pending_points
}
function validDetail(detail: ReviewDetail, id: string) {
  if (!validItem(detail) || detail.candidate_id !== id || !Array.isArray(detail.bundle_members)
    || !Array.isArray(detail.bundle_removals) || !Array.isArray(detail.points)
    || !(detail.head_release_id === null || typeof detail.head_release_id === 'string')) return false
  const seen = new Set<string>()
  const members = new Map(detail.bundle_members.map(member => [member.logical_slug, member]))
  return detail.points.every(point => {
    if (!point || typeof point.slug !== 'string' || !point.slug || seen.has(point.slug)
      || !['claim', 'member', 'removal'].includes(point.kind) || !statuses.includes(point.status)
      || typeof point.blocker !== 'string') return false
    seen.add(point.slug)
    return point.kind === 'removal' ? detail.bundle_removals.includes(point.slug)
      : members.has(point.slug) && (point.kind !== 'claim' || members.get(point.slug)?.kind === 'claim')
  }) && detail.point_count === detail.points.length
    && detail.pending_points === detail.points.filter(point => point.status === 'pending').length
}
function validResult(result: PointResult, input: PointDecisionInput) {
  if (!result || !statuses.includes(result.status) || !Array.isArray(result.points)
    || result.points.length !== input.slugs.length) return false
  const expected = new Set(input.slugs)
  const status = input.outcome === 'approve' ? 'released' : 'rejected'
  if (!result.points.every(point => point && point.status === status && expected.delete(point.slug))) return false
  return input.outcome === 'approve'
    ? typeof result.release_id === 'string' && !!result.release_id && Number.isSafeInteger(result.epoch) && result.epoch! > 0
    : result.release_id === null && result.epoch === null
}

export function useReviews(spaceId: Readonly<Ref<string>>) {
  const tab = ref<ReviewTab>('pending'), state = ref<'loading' | 'failed' | 'ready'>('loading')
  const release = shallowRef<Release | null>(null), entries = ref<ReviewEntry[]>([]), notice = ref(false)
  let generation = 0
  // Each list read owns the lifetime of its paired Release, sections and decisions.
  async function load(decidedElsewhere = false): Promise<ReviewFocus> {
    const version = ++generation, space = spaceId.value, status = tab.value
    const valid = () => version === generation
    entries.value = []; release.value = null; state.value = 'loading'; notice.value = decidedElsewhere
    try {
      const [items, snapshot] = await Promise.all([listReviews(space, status), readRelease(space).catch(() => null)])
      if (valid()) {
        if (!Array.isArray(items) || !items.every(validItem)) throw new EnterpriseError('INVALID_RESPONSE')
        release.value = snapshot
        const unique = [...new Map(items.filter(item => status === 'pending' ? item.status === 'pending'
          : item.status !== 'pending').map(item => [item.candidate_id, item])).values()]
        if (status === 'pending') unique.sort((a, b) => a.created_at.localeCompare(b.created_at))
        entries.value = unique.map(item => reactive({ item, detail: null, snapshot: null, points: [],
          phase: 'idle' as const, expanded: false, busy: false, error: '', notice: false, operation: 0 }))
        state.value = 'ready'
        if (status === 'pending' && entries.value[0]) void readEntry(entries.value[0])
      }
    } catch { if (valid()) state.value = 'failed' }
    return { valid, target: 'tab', id: '' }
  }
  function current(entry: ReviewEntry, version: number, operation: number) {
    return generation === version && entry.operation === operation && entries.value.includes(entry)
  }
  async function readEntry(entry: ReviewEntry): Promise<ReviewFocus | null> {
    if (!entries.value.includes(entry) || entry.busy) return null
    const version = generation, operation = ++entry.operation, space = spaceId.value
    const valid = () => current(entry, version, operation)
    entry.expanded = true; entry.phase = 'loading'; entry.error = ''; entry.detail = null; entry.points = []
    try {
      const detail = await readReview(space, entry.item.candidate_id)
      if (!valid()) return null
      if (!validDetail(detail, entry.item.candidate_id)) throw new EnterpriseError('INVALID_RESPONSE')
      let snapshot = release.value
      // Read the exact Head used for this detail; a newer active release is not its comparison.
      if (detail.head_release_id !== (snapshot?.id ?? null)) {
        snapshot = detail.head_release_id ? await readRelease(space, detail.head_release_id).catch(() => null) : null
      }
      if (!valid()) return null
      entry.snapshot = snapshot
      entry.detail = detail; entry.item = { ...entry.item, ...detail }
      entry.points = detail.points.map(point => ({ point, result: null, error: '' }))
      entry.phase = 'ready'
    } catch (error) { if (valid()) { entry.error = failure(error); entry.phase = 'failed' } }
    return { valid, target: 'detail', id: entry.item.candidate_id }
  }
  async function open(entry: ReviewEntry): Promise<ReviewFocus | null> {
    if (!entries.value.includes(entry) || entry.busy || entry.phase === 'loading') return null
    if (entry.phase === 'ready') { entry.expanded = !entry.expanded; return null }
    return readEntry(entry)
  }
  async function decide(entry: ReviewEntry, input: PointDecisionInput): Promise<ReviewFocus | null> {
    const reason = trimReviewReason(input.reason), count = reviewReasonLength(reason)
    const selected = input.slugs.map(slug => entry.points.find(value => value.point.slug === slug))
    if (!entries.value.includes(entry) || tab.value !== 'pending' || entry.phase !== 'ready' || entry.busy
      || !count || count > 2000 || !input.slugs.length || input.slugs.length > MAX_REVIEW_POINTS
      || new Set(input.slugs).size !== input.slugs.length
      || selected.some(value => !value || !pendingPoint(value))
      || (input.outcome === 'approve' && (!canCompare(entry) || selected.some(value => value!.point.blocker)))) return null
    const version = generation, operation = ++entry.operation, space = spaceId.value
    const valid = () => current(entry, version, operation)
    entry.busy = true; entry.error = ''
    selected.forEach(value => { value!.error = '' })
    try {
      const result = await decidePoints(space, entry.item.candidate_id, [...input.slugs], input.outcome, reason)
      if (!valid()) return null
      if (!validResult(result, input)) throw new EnterpriseError('INVALID_RESPONSE')
      for (const value of selected) {
        value!.result = { status: input.outcome === 'approve' ? 'released' : 'rejected', epoch: result.epoch, reason }
      }
      entry.item.pending_points = entry.points.filter(pendingPoint).length
      entry.item.status = result.status
      return { valid, target: 'point-state', id: entry.item.candidate_id, slug: input.slugs[0] }
    } catch (error) {
      if (!valid()) return null
      const code = failure(error)
      if (code === 'CANDIDATE_DECIDED') return await load(true)
      if (code === 'MEMBER_DECIDED' || code === 'NEEDS_REBASE') {
        entry.busy = false; entry.notice = code === 'MEMBER_DECIDED'
        return await readEntry(entry)
      }
      selected.forEach(value => { value!.error = code })
      if (selected.length > 1) entry.error = code
      return { valid, target: 'point-error', id: entry.item.candidate_id, slug: input.slugs[0] }
    } finally { if (valid()) entry.busy = false }
  }
  function selectTab(next: ReviewTab) { if (next !== tab.value) { tab.value = next; void load() } }
  watch(spaceId, () => { tab.value = 'pending'; void load() }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { generation++ })
  return { tab, state, release, entries, notice, load, open, reload: readEntry, decide, selectTab }
}
