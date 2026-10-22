<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RouteLocationRaw } from 'vue-router'
import { originLabel, stateLabel } from './fieldLabels'
import OutlineList from './OutlineList.vue'
import type { FieldView } from './releaseView'
import { valueOutline } from './valueOutline'

// Values longer than this open in a compact version with a switch to the full one (S3d-4 §3.2).
const LONG_CHARS = 240
// Nearly every field is sourced, so that label is kept for screen readers only; the page says so.
const SOURCE_SUPPORTED = 'SOURCE_SUPPORTED'

// editable offers the expert edit (S9b); only the entity page sets it, for administrators.
const props = defineProps<{
  field: FieldView; conceptRoute?: RouteLocationRaw; anchorId?: string; previous?: FieldView | null; editable?: boolean
}>()
const emit = defineEmits<{ open: [evidence: number]; openPrevious: [evidence: number]; edit: [] }>()
const { t } = useI18n()
const full = ref(false)
const expanded = ref(false), previousId = `previous-${useId()}`

const value = computed(() => (props.field.state === 'present' ? props.field.value : null))
const outline = computed(() => (value.value === null ? null : valueOutline(value.value)))
const long = computed(() => {
  const text = value.value === null ? '' : Array.isArray(value.value) ? value.value.join('') : value.value
  return text.length > LONG_CHARS
})
const listed = computed(() => (outline.value?.items.length ?? 0) > 0)

watch(() => props.field.slug, () => { full.value = false })
watch(() => [props.field.slug, props.previous], () => { expanded.value = false })
</script>

<template>
  <div :id="anchorId || field.slug.slice(field.slug.lastIndexOf('/') + 1)" :class="['ek-field', { 'ek-field--generated': field.origin === 'MODEL_GENERATED' }]" :data-field="field.slug" tabindex="-1">
    <div class="ek-field__head">
      <h3 class="ek-field__title"><RouterLink v-if="conceptRoute" :to="conceptRoute">{{ field.title }}</RouterLink><template v-else>{{ field.title }}</template></h3>
      <button v-if="editable" type="button" data-expert-edit class="ek-link-button ek-field__edit" :aria-label="`${t('enterpriseKnowledge.expert.edit')} ${field.title}`" @click="emit('edit')">{{ t('enterpriseKnowledge.expert.edit') }}</button>
      <button v-if="previous !== undefined" type="button" data-field-updated class="ek-link-button ek-field__updated" :aria-expanded="expanded" :aria-controls="previousId" @click="expanded = !expanded">{{ t('enterpriseKnowledge.changes.updated') }}</button>
    </div>
    <div :class="['ek-field__value', { 'ek-field__value--clamped': long && !full && !listed }]">
      <template v-if="field.state === 'present'">
        <template v-if="outline && listed">
          <p v-if="outline.intro" :class="['ek-outline__intro', { 'ek-outline__intro--clamped': long && !full }]">{{ outline.intro }}</p>
          <OutlineList :items="outline.items" :collapsible="long" :open="full" />
        </template>
        <span v-else class="ek-field__text">{{ outline?.intro || '—' }}</span>
      </template>
      <span v-else class="ek-field__state">{{ stateLabel(t, field.state) }}</span>
    </div>
    <div v-if="expanded && previous !== undefined" :id="previousId" data-field-previous class="ek-field__previous">
      <p class="ek-page__meta">{{ t('enterpriseKnowledge.changes.before') }}</p>
      <EnterpriseField v-if="previous" :field="previous" :anchor-id="`${previousId}-value`" @open="emit('openPrevious', $event)" />
      <p v-else class="ek-page__meta">{{ t('enterpriseKnowledge.changes.notPreviouslyPresent') }}</p>
    </div>
    <!-- S3d-5: the switch on the left, origin and sources at the bottom right (user 2026-10-18). -->
    <div v-if="long || field.origin || field.evidenceCount" class="ek-field__foot">
      <span v-if="long" class="ek-field__toggle">
        <span v-if="listed && !full">{{ t('enterpriseKnowledge.field.items', { count: outline?.items.length }) }}</span>
        <button type="button" data-toggle class="ek-link-button" :aria-expanded="full" @click="full = !full">
          {{ full ? t('enterpriseKnowledge.field.compact') : t('enterpriseKnowledge.field.full') }}
        </button>
      </span>
      <span class="ek-field__meta">
        <span
          v-if="field.origin"
          data-origin
          :class="[
            'ek-origin',
            {
              'ek-origin--generated': field.origin === 'MODEL_GENERATED',
              'ek-sr-only': field.origin === SOURCE_SUPPORTED,
            },
          ]"
        >{{ originLabel(t, field.origin) }}</span>
        <button
          v-for="index in field.evidenceCount"
          :key="index"
          type="button"
          class="ek-link-button ek-source ek-source-chip"
          @click="emit('open', index - 1)"
        >{{ t('enterpriseKnowledge.entity.source', { n: index }) }}</button>
      </span>
    </div>
  </div>
</template>
