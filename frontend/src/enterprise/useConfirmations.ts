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
// 'moved': an answer recorded on 待处理 moves the item to 已处理 (S5b-3e), the card leaves the list.
export type AnswerResult = 'answered' | 'moved' | 'closed' | 'failed' | 'stale'

export const maxNote = 1000
// The server trims with Go's strings.TrimSpace, where U+0085 is a space and U+FEFF is not
// (String.prototype.trim says the opposite), then counts code points.
const SPACE = '[\\t\\n\\v\\f\\r \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]'
const EDGES = new RegExp(`^${SPACE}+|${SPACE}+$`, 'gu')
export const trimNote = (note: string) => note.replace(EDGES, '')
export const noteLength = (note: string) => Array.from(trimNote(note)).length
// The server then refuses control characters other than a newline (Go unicode.IsControl).
const CONTROL = new RegExp('[\\u0000-\\u0009\\u000b-\\u001f\\u007f-\\u009f]', 'u')
export const noteHasControl = (note: string) => CONTROL.test(trimNote(note))

function startDraft(item: ConfirmationItem): ConfirmationDraft {
  return { base: item.answer?.id ?? '', option: item.answer?.option_key ?? '', note: item.answer?.note ?? '', busy: false, error: '' }
}

// Submitting again is pointless unless it records a different choice or note.
export function canAnswer(item: ConfirmationItem, draft: ConfirmationDraft): boolean {
  if (item.closure || draft.busy || noteLength(draft.note) > maxNote || noteHasControl(draft.note)) return false
  if (!item.options.some(option => option.key === draft.option)) return false
  return !item.answer || draft.option !== item.answer.option_key || trimNote(draft.note) !== trimNote(item.answer.note)
}

export function useConfirmations(spaceId: Readonly<Ref<string>>) {
  const tab = ref<ConfirmationTab>('open')
  const state = ref<'loading' | 'failed' | 'ready'>('loading')
  const items = ref<ConfirmationItem[]>([])
  const drafts = reactive(new Map<string, ConfirmationDraft>())
  // The title of an item someone else closed while this page offered it.
  const notice = ref('')
  // The option label of the last answer that moved an item from 待处理 to 已处理.
  const moved = ref('')
  // `scope` changes with the Space, `request` with every list read. A submission answers only the
  // list it was made from: once the list was read again it shows the server's state instead.
  let scope = 0, request = 0

  async function load() {
    const current = ++request, currentScope = scope, space = spaceId.value, status = tab.value
    state.value = 'loading'; items.value = []; notice.value = ''; moved.value = ''
    try {
      // An answer decides the tab (S5b-3e): 待处理 holds open items nobody answered; 已处理 holds the
      // answered open items, still waiting for the system, ahead of the closed ones.
      const [open, closed] = await Promise.all([
        listConfirmations(space, 'open'), status === 'closed' ? listConfirmations(space, 'closed') : [],
      ])
      if (current !== request || currentScope !== scope) return
      const mine = (item: ConfirmationItem) => item.space_id === space
      const shown = status === 'open'
        ? open.filter(item => mine(item) && !item.closure && !item.answer)
        : [...closed.filter(item => mine(item) && !!item.closure), ...open.filter(item => mine(item) && !item.closure && !!item.answer)]
      // A closed copy wins over an open one the same item still had in the other list.
      const unique = new Map<string, ConfirmationItem>()
      for (const item of shown) if (!unique.get(item.id)?.closure) unique.set(item.id, item)
      items.value = status === 'open' ? [...unique.values()]
        : [...[...unique.values()].filter(item => !item.closure), ...[...unique.values()].filter(item => !!item.closure)]
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
    const current = scope, listed = request, space = spaceId.value, option = entry.option
    const left = () => current !== scope || listed !== request
    entry.busy = true; entry.error = ''
    try {
      const recorded = await answerConfirmation(space, item.id, option, entry.note)
      if (left()) return 'stale'
      if (recorded.item_id !== item.id || recorded.option_key !== option) throw new EnterpriseError('INVALID_RESPONSE')
      const answered = { ...item, answer: recorded }
      if (!item.answer && tab.value === 'open') {
        items.value = items.value.filter(existing => existing.id !== item.id)
        drafts.delete(item.id)
        moved.value = item.options.find(choice => choice.key === recorded.option_key)?.label ?? option
        return 'moved'
      }
      items.value = items.value.map(existing => existing.id === item.id ? answered : existing)
      drafts.set(item.id, startDraft(answered))
      return 'answered'
    } catch (error) {
      if (left()) return 'stale'
      const code = error instanceof EnterpriseError ? error.code : ''
      if (code === 'CONFIRMATION_CLOSED') {
        drafts.delete(item.id)
        const reload = load(), reloaded = request
        notice.value = item.title
        await reload
        // A refresh replaced by a later list read is not this page's any more: leave its focus alone.
        return current === scope && reloaded === request ? 'closed' : 'stale'
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
  return { tab, state, items, drafts, notice, moved, load, selectTab, answer }
}
