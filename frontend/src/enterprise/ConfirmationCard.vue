<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { EnterpriseError, readConfirmationFile, type ConfirmationItem } from './enterpriseApi'
import { canAnswer, maxNote, noteHasControl, noteLength, type ConfirmationDraft } from './useConfirmations'

const props = defineProps<{ item: ConfirmationItem; draft?: ConfirmationDraft }>()
const emit = defineEmits<{ option: [key: string]; note: [value: string]; submit: [] }>()
const { t, locale } = useI18n()
const groupId = useId(), noteId = useId()
const label = (key?: string) => props.item.options.find(option => option.key === key)?.label
const length = computed(() => noteLength(props.draft?.note ?? ''))
const controlled = computed(() => noteHasControl(props.draft?.note ?? ''))
const ready = computed(() => !!props.draft && canAnswer(props.item, props.draft))
const waiting = computed(() => {
  const chosen = label(props.item.answer?.option_key)
  return chosen ? t('enterpriseKnowledge.confirm.answered', { option: chosen }) : t('enterpriseKnowledge.confirm.waiting')
})
// Name an applied option only when the closure names the answer shown here; never guess one.
const applied = computed(() => {
  const { closure, answer } = props.item
  return closure?.reason === 'applied' && answer && closure.answer_id === answer.id ? answer : undefined
})
const outcome = computed(() => {
  if (props.item.closure?.reason === 'obsolete') return t('enterpriseKnowledge.confirm.obsolete')
  const chosen = label(applied.value?.option_key)
  return chosen ? t('enterpriseKnowledge.confirm.applied', { option: chosen }) : t('enterpriseKnowledge.confirm.handled')
})
const closedAt = computed(() => {
  const raw = props.item.closure?.closed_at ?? '', date = new Date(raw)
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString(locale.value)
})
const failure = computed(() => ({
  denied: t('enterpriseKnowledge.confirm.denied'),
  invalid: t('enterpriseKnowledge.confirm.invalid'),
  failed: t('enterpriseKnowledge.confirm.submitFailed'),
  '': '',
})[props.draft?.error ?? ''])

const fileBusy = ref(false), fileError = ref('')
let activeFile: { controller: AbortController; tab: Window } | undefined
const fileUrls = new Map<string, ReturnType<typeof setTimeout>>()

function closeTab(tab: Window) {
  try { tab.close() } catch { /* A tab navigated or closed by the user must not prevent cleanup. */ }
}
function releaseFileUrl(url: string) {
  clearTimeout(fileUrls.get(url))
  fileUrls.delete(url)
  URL.revokeObjectURL(url)
}
function clearFile() {
  const pending = activeFile
  activeFile = undefined
  pending?.controller.abort()
  if (pending) closeTab(pending.tab)
  for (const url of fileUrls.keys()) releaseFileUrl(url)
  fileBusy.value = false
  fileError.value = ''
}
// A reused card must not deliver a previous item's response to its new source.
watch([() => props.item.space_id, () => props.item.id, () => props.item.source_ref], clearFile, { flush: 'sync' })
onBeforeUnmount(clearFile)

async function openFile() {
  if (fileBusy.value || !props.item.source_ref) return
  fileError.value = ''
  let tab: Window | null
  try { tab = window.open('', '_blank') } catch {
    fileError.value = 'fileFailed'
    return
  }
  if (!tab) {
    fileError.value = 'fileBlocked'
    return
  }
  const request = { controller: new AbortController(), tab }
  activeFile = request
  fileBusy.value = true
  let url: string | undefined
  try {
    const blob = await readConfirmationFile(props.item.space_id, props.item.id, request.controller.signal)
    if (activeFile !== request) return
    if (tab.closed) throw new Error('File tab closed')
    url = URL.createObjectURL(blob)
    tab.location.href = url
    const openedUrl = url
    fileUrls.set(openedUrl, setTimeout(() => releaseFileUrl(openedUrl), 60_000))
    url = undefined // The timer (or unmount) now owns this successfully opened URL.
  } catch (error) {
    if (url) URL.revokeObjectURL(url)
    if (activeFile !== request) return
    closeTab(tab)
    const code = error instanceof EnterpriseError ? error.code : ''
    fileError.value = code === 'SOURCE_NOT_FOUND' ? 'fileMissing' : code === 'SOURCE_INTEGRITY' ? 'fileChanged' : 'fileFailed'
  } finally {
    if (activeFile === request) {
      activeFile = undefined
      fileBusy.value = false
    }
  }
}
</script>

<template>
  <article class="ek-confirm-card" :data-confirm-item="item.id" :aria-busy="draft?.busy ?? false">
    <fieldset v-if="!item.closure && draft" class="ek-confirm-card__choice">
      <legend><h2 class="ek-confirm-card__title">{{ item.title }}</h2></legend>
      <p v-if="item.detail" class="ek-confirm-card__detail" data-confirm-detail>{{ item.detail }}</p>
      <div class="ek-confirm-options">
        <label v-for="option in item.options" :key="option.key" class="ek-confirm-option">
          <input type="radio" :name="groupId" :value="option.key" :checked="draft.option === option.key"
            :disabled="draft.busy" :data-confirm-option="option.key" @change="emit('option', option.key)" />
          <span>{{ option.label }}</span>
        </label>
      </div>
      <label class="ek-confirm-card__label" :for="noteId">{{ t('enterpriseKnowledge.confirm.note') }}</label>
      <textarea :id="noteId" :value="draft.note" :disabled="draft.busy" :aria-invalid="length > maxNote || controlled"
        :aria-describedby="controlled ? `${noteId}-hint ${noteId}-invalid` : `${noteId}-hint`" rows="2"
        :placeholder="t('enterpriseKnowledge.confirm.notePlaceholder')" @input="emit('note', ($event.target as HTMLTextAreaElement).value)" />
      <span :id="`${noteId}-hint`" class="ek-confirm-limit" :class="{ 'ek-confirm-limit--invalid': length > maxNote }">{{ t('enterpriseKnowledge.confirm.noteLimit', { count: length }) }}</span>
      <p v-if="controlled" :id="`${noteId}-invalid`" class="ek-confirm-error ek-confirm-note-invalid">{{ t('enterpriseKnowledge.confirm.noteInvalid') }}</p>
      <div class="ek-confirm-card__actions">
        <p v-if="item.answer" class="ek-confirm-state" data-confirm-state tabindex="-1">{{ waiting }}</p>
        <button type="button" class="ek-button ek-confirm-submit" data-confirm-submit :disabled="!ready" @click="emit('submit')">
          {{ item.answer ? t('enterpriseKnowledge.confirm.change') : t('enterpriseKnowledge.confirm.submit') }}
        </button>
      </div>
      <p v-if="draft.busy" role="status" class="ek-page__meta">{{ t('enterpriseKnowledge.confirm.submitting') }}</p>
      <p v-if="draft.error" role="alert" class="ek-confirm-error">{{ failure }}</p>
    </fieldset>
    <template v-else-if="item.closure">
      <h2 class="ek-confirm-card__title">{{ item.title }}</h2>
      <p v-if="item.detail" class="ek-confirm-card__detail" data-confirm-detail>{{ item.detail }}</p>
      <div class="ek-confirm-card__result">
        <p class="ek-confirm-state" data-confirm-state :data-reason="item.closure?.reason">{{ outcome }}</p>
        <template v-if="applied">
          <p class="ek-confirm-note">{{ applied.note || t('enterpriseKnowledge.confirm.noNote') }}</p>
          <p class="ek-page__meta">{{ t('enterpriseKnowledge.confirm.answerer') }} {{ applied.answerer }}</p>
        </template>
        <time class="ek-page__meta" :datetime="item.closure?.closed_at">{{ t('enterpriseKnowledge.confirm.closedAt', { time: closedAt }) }}</time>
      </div>
    </template>
    <div v-if="item.source_ref" class="ek-confirm-card__file">
      <button type="button" class="ek-button ek-confirm-file" data-confirm-file :disabled="fileBusy" @click="openFile">
        {{ t('enterpriseKnowledge.confirm.openFile') }}
      </button>
      <p v-if="fileBusy" role="status" class="ek-page__meta">{{ t('enterpriseKnowledge.confirm.openingFile') }}</p>
      <p v-if="fileError" role="alert" class="ek-confirm-error" data-confirm-file-error>{{ t(`enterpriseKnowledge.confirm.${fileError}`) }}</p>
    </div>
  </article>
</template>
