import { onScopeDispose, reactive, ref, watch, type Ref } from 'vue'
import { answerConfirmation, EnterpriseError, listConfirmations, type ConfirmationItem } from './enterpriseApi'

export type ConfirmationTab = 'open' | 'closed'
// `base` is the answer a draft started from; a newer answer from the server restarts the draft.
export interface ConfirmationDraft {
  base: string
  option: string
  note: string
  busy: boolean
  error: '' | 'failed' | 'denied' | 'invalid'
}
export type AnswerResult = 'answered' | 'closed' | 'failed' | 'stale'

export const maxNote = 1000
// The server trims the note and counts code points.
export const noteLength = (note: string) => Array.from(note.trim()).length

function startDraft(item: ConfirmationItem): ConfirmationDraft {
  return { base: item.answer?.id ?? '', option: item.answer?.option_key ?? '', note: item.answer?.note ?? '', busy: false, error: '' }
}

// Submitting again is pointless unless it records a different choice or note.
export function canAnswer(item: ConfirmationItem, draft: ConfirmationDraft): boolean {
  if (item.closure || draft.busy || noteLength(draft.note) > maxNote) return false
  if (!item.options.some(option => option.key === draft.option)) return false
  return !item.answer || draft.option !== item.answer.option_key || draft.note.trim() !== item.answer.note.trim()
}

export function useConfirmations(spaceId: Readonly<Ref<string>>) {
  const tab = ref<ConfirmationTab>('open')
  const state = ref<'loading' | 'failed' | 'ready'>('loading')
  const items = ref<ConfirmationItem[]>([])
  const drafts = reactive(new Map<string, ConfirmationDraft>())
  // The title of an item someone else closed while this page offered it.
  const notice = ref('')
  let scope = 0, request = 0

  async function load() {
    const current = ++request, currentScope = scope, space = spaceId.value, status = tab.value
    state.value = 'loading'; items.value = []; notice.value = ''
    try {
      const listed = await listConfirmations(space, status)
      if (current !== request || currentScope !== scope) return
      const unique = new Map(listed
        .filter(item => item.space_id === space && (status === 'closed') === !!item.closure)
        .map(item => [item.id, item]))
      items.value = [...unique.values()]
      for (const item of items.value) {
        if (!item.closure && drafts.get(item.id)?.base !== (item.answer?.id ?? '')) drafts.set(item.id, startDraft(item))
      }
      state.value = 'ready'
    } catch {
      if (current === request && currentScope === scope) state.value = 'failed'
    }
  }
  function selectTab(next: ConfirmationTab) {
    if (next === tab.value) return
    tab.value = next
    void load()
  }
  async function answer(item: ConfirmationItem): Promise<AnswerResult> {
    const entry = drafts.get(item.id)
    if (!entry || item.space_id !== spaceId.value || !canAnswer(item, entry)) return 'failed'
    const current = scope, space = spaceId.value, option = entry.option
    entry.busy = true; entry.error = ''
    try {
      const recorded = await answerConfirmation(space, item.id, option, entry.note)
      if (current !== scope) return 'stale'
      if (recorded.item_id !== item.id || recorded.option_key !== option) throw new EnterpriseError('INVALID_RESPONSE')
      const answered = { ...item, answer: recorded }
      items.value = items.value.map(existing => existing.id === item.id ? answered : existing)
      drafts.set(item.id, startDraft(answered))
      return 'answered'
    } catch (error) {
      if (current !== scope) return 'stale'
      const code = error instanceof EnterpriseError ? error.code : ''
      if (code === 'CONFIRMATION_CLOSED') {
        drafts.delete(item.id)
        const reload = load()
        notice.value = item.title
        await reload
        return current === scope ? 'closed' : 'stale'
      }
      const denied = error instanceof EnterpriseError && (error.status === 403 || code === 'RELEASE_ACCESS_DENIED')
      entry.error = denied ? 'denied' : code === 'ANSWER_INVALID' ? 'invalid' : 'failed'
      return 'failed'
    } finally {
      if (current === scope) entry.busy = false
    }
  }
  watch(spaceId, () => {
    scope++; request++; drafts.clear(); items.value = []; tab.value = 'open'; void load()
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { scope++; request++ })
  return { tab, state, items, drafts, notice, load, selectTab, answer }
}
