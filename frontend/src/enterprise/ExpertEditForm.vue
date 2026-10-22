<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { EnterpriseError, submitExpertEdit, type ExpertEditInput, type Release } from './enterpriseApi'
import { expertEditFailure, stateLabel } from './fieldLabels'

// The expert edit of one claim of the shown release (S9b Spec §2.3). Saving publishes at once;
// the server re-checks role, release and digest (S9a), so a refusal keeps what was typed.
const MAX_REASON = 2000
type State = ExpertEditInput['state']

const props = defineProps<{ spaceId: string; release: Release; slug: string; title: string }>()
const emit = defineEmits<{ published: [result: { releaseId: string; epoch: number }]; reload: []; cancel: [] }>()
const { t } = useI18n()

const member = computed(() => props.release.members.find(item => item.logical_slug === props.slug))
const currentState = computed(() => String(member.value?.payload?.state ?? ''))
const currentValue = computed(() => member.value?.payload?.value)
// Pre-fill only text (a string, or a string list one item per line); other values start empty.
const currentText = computed(() => {
  const value = currentValue.value
  if (typeof value === 'string') return value
  if (Array.isArray(value) && value.every(item => typeof item === 'string')) return value.join('\n')
  return ''
})
// What the expert compares against: every present value is shown, whatever its type.
const currentShown = computed(() => {
  const value = currentValue.value
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(item => (typeof item === 'string' ? item : JSON.stringify(item))).join('\n')
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
})
// A scalar typed back unchanged is no change; the server would refuse it (S9a).
const currentComparable = computed(() => {
  const value = currentValue.value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return currentText.value
})

const state = ref<State>('present')
const value = ref('')
const reason = ref('')
const busy = ref(false)
const failure = ref<{ text: string; reload: boolean } | null>(null)

function reset() {
  const known: State[] = ['present', 'absent_explicitly', 'unknown']
  state.value = known.includes(currentState.value as State) ? currentState.value as State : 'present'
  value.value = currentState.value === 'present' ? currentText.value : ''
  reason.value = ''
  failure.value = null
}
watch(() => [props.release.id, props.slug], reset, { immediate: true })

const reasonLength = computed(() => [...reason.value].length)
const changed = computed(() => state.value !== currentState.value
  || (state.value === 'present' && value.value.trim() !== currentComparable.value.trim()))
const ready = computed(() => !busy.value && member.value !== undefined && reason.value.trim() !== ''
  && reasonLength.value <= MAX_REASON && (state.value !== 'present' || value.value.trim() !== '') && changed.value)

const states = computed(() => [
  { value: 'present' as const, label: t('enterpriseKnowledge.expert.statePresent') },
  { value: 'absent_explicitly' as const, label: stateLabel(t, 'absent_explicitly') },
  { value: 'unknown' as const, label: stateLabel(t, 'unknown') },
])

async function save() {
  if (!ready.value || !member.value) return
  busy.value = true
  failure.value = null
  try {
    const result = await submitExpertEdit(props.spaceId, {
      base_release_id: props.release.id, member_slug: props.slug, base_member_digest: member.value.member_digest,
      state: state.value, value: state.value === 'present' ? value.value.trim() : '', reason: reason.value.trim(),
    })
    emit('published', { releaseId: result.release_id, epoch: result.epoch })
  } catch (error) {
    const typed = error instanceof EnterpriseError ? error : new EnterpriseError('REQUEST_FAILED')
    failure.value = expertEditFailure(t, typed.code, typed.status)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form class="ek-expert-form" @submit.prevent>
    <p class="ek-expert-form__current">
      <span class="ek-page__meta">{{ t('enterpriseKnowledge.expert.current') }}</span>
      <span data-current>{{ currentState === 'present' ? currentShown : stateLabel(t, currentState) }}</span>
    </p>
    <fieldset data-state class="ek-expert-form__states">
      <legend>{{ t('enterpriseKnowledge.expert.state') }}</legend>
      <label v-for="option in states" :key="option.value">
        <input v-model="state" type="radio" name="expert-state" :value="option.value" :disabled="busy">
        {{ option.label }}
      </label>
    </fieldset>
    <label v-if="state === 'present'" class="ek-expert-form__field">
      <span>{{ t('enterpriseKnowledge.expert.value') }}</span>
      <textarea v-model="value" data-value rows="4" :disabled="busy" />
    </label>
    <label class="ek-expert-form__field">
      <span>{{ t('enterpriseKnowledge.expert.reason') }}</span>
      <textarea v-model="reason" data-reason rows="3" required :disabled="busy" />
      <span :class="['ek-page__meta', { 'ek-expert-form__over': reasonLength > MAX_REASON }]">
        {{ t('enterpriseKnowledge.expert.reasonCount', { count: reasonLength, max: MAX_REASON }) }}
      </span>
    </label>
    <p class="ek-page__note">{{ t('enterpriseKnowledge.expert.hint') }}</p>
    <p v-if="busy" role="status" class="ek-status">{{ t('enterpriseKnowledge.expert.saving') }}</p>
    <div v-if="failure" role="alert" class="ek-alert">
      <span>{{ failure.text }}</span>
      <button v-if="failure.reload" type="button" data-reload class="ek-button" @click="emit('reload')">
        {{ t('enterpriseKnowledge.expert.reload') }}
      </button>
    </div>
    <div class="ek-expert-form__actions">
      <button type="submit" data-submit class="ek-button ek-button--primary" :disabled="!ready" @click.prevent="save">
        {{ t('enterpriseKnowledge.expert.submit') }}
      </button>
      <button type="button" class="ek-button" :disabled="busy" @click="emit('cancel')">
        {{ t('enterpriseKnowledge.expert.cancel') }}
      </button>
    </div>
  </form>
</template>

<style src="./expertEdit.css"></style>
