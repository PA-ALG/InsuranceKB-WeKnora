import { onScopeDispose, reactive, ref, watch, type Ref } from 'vue'
import { EnterpriseError, listSamples, readRelease, submitVerdict, type Release, type SpotSample, type SpotVerdict } from './enterpriseApi'
import { sampledField } from './spotCheckView'

export interface SpotDraft { note: string; busy: boolean; error: '' | 'failed' | 'denied' }
export interface SpotRelease { state: 'loading' | 'failed' | 'ready'; release?: Release }
export const noteLength = (note: string) => Array.from(note.trim()).length

export function useSpotChecks(spaceId: Readonly<Ref<string>>) {
  const tab = ref<'pending' | 'decided'>('pending')
  const state = ref<'loading' | 'failed' | 'ready'>('loading')
  const samples = ref<SpotSample[]>([])
  const releases = reactive(new Map<string, SpotRelease>())
  const drafts = reactive(new Map<string, SpotDraft>())
  // Cache only inside this mounted Space. A failed read can be explicitly retried.
  const reads = new Map<string, Promise<Release>>()
  const completed = new Map<string, SpotSample>()
  let scope = 0, request = 0

  function draft(id: string): SpotDraft {
    if (!drafts.has(id)) drafts.set(id, { note: '', busy: false, error: '' })
    return drafts.get(id)!
  }
  async function loadRelease(id: string) {
    if (reads.has(id)) return
    const current = scope, space = spaceId.value
    releases.set(id, { state: 'loading' })
    const read = (async () => {
      if (!id.trim() || id === 'active') throw new EnterpriseError('RELEASE_NOT_FOUND')
      const release = await readRelease(space, id)
      if (release.id !== id) throw new EnterpriseError('INVALID_RESPONSE')
      return release
    })()
    reads.set(id, read)
    try {
      const release = await read
      if (current === scope) releases.set(id, { state: 'ready', release })
    } catch {
      if (current === scope) { reads.delete(id); releases.set(id, { state: 'failed' }) }
    }
  }
  async function load() {
    const current = ++request, currentScope = scope, space = spaceId.value, status = tab.value
    state.value = 'loading'; samples.value = []
    try {
      const listed = await listSamples(space, status)
      if (current !== request || currentScope !== scope) return
      const unique = new Map(listed.filter(sample => sample.space_id === space).map(sample => [sample.id, sample]))
      for (const [id, sample] of completed) {
        if (status === 'pending') unique.delete(id)
        else if (!unique.has(id)) unique.set(id, sample)
      }
      samples.value = [...unique.values()].filter(sample => status === 'pending' ? !sample.verdict : !!sample.verdict)
      state.value = 'ready'
      for (const id of new Set(samples.value.map(sample => sample.release_id))) void loadRelease(id)
    } catch {
      if (current === request && currentScope === scope) state.value = 'failed'
    }
  }
  function selectTab(next: 'pending' | 'decided') {
    if (next === tab.value) return
    tab.value = next
    void load()
  }
  async function decide(sample: SpotSample, outcome: SpotVerdict['outcome']): Promise<boolean> {
    const entry = draft(sample.id)
    if (entry.busy || completed.has(sample.id) || sample.verdict || sample.space_id !== spaceId.value
      || noteLength(entry.note) > 1000 || !sampledField(sample, releases.get(sample.release_id)?.release)) return false
    const current = scope, space = spaceId.value
    entry.busy = true; entry.error = ''
    try {
      const verdict = await submitVerdict(space, sample.id, outcome, entry.note)
      if (current !== scope) return false
      if (verdict.sample_id !== sample.id) throw new EnterpriseError('INVALID_RESPONSE')
      const decided = { ...sample, verdict }
      completed.set(sample.id, decided)
      samples.value = samples.value.filter(item => item.id !== sample.id)
      if (tab.value === 'decided') samples.value.push(decided)
      drafts.delete(sample.id)
      return true
    } catch (error) {
      if (current === scope) entry.error = error instanceof EnterpriseError
        && (error.status === 403 || error.code === 'RELEASE_ACCESS_DENIED') ? 'denied' : 'failed'
      return false
    } finally {
      if (current === scope) entry.busy = false
    }
  }
  watch(spaceId, () => {
    scope++; request++; reads.clear(); releases.clear(); drafts.clear(); completed.clear()
    samples.value = []; tab.value = 'pending'; void load()
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { scope++; request++ })
  return { tab, state, samples, releases, draft, load, loadRelease, selectTab, decide }
}
