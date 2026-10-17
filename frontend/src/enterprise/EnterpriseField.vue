<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { originLabel, stateLabel } from './fieldLabels'
import type { FieldView } from './releaseView'

defineProps<{ field: FieldView }>()
const emit = defineEmits<{ open: [evidence: number] }>()
const { t } = useI18n()
</script>

<template>
  <div class="ek-field" :data-field="field.slug">
    <div class="ek-field__title">{{ field.title }}</div>
    <div class="ek-field__value">
      <template v-if="field.state === 'present'">
        <ul v-if="Array.isArray(field.value)" class="ek-field__list">
          <li v-for="(item, index) in field.value" :key="index">{{ item }}</li>
        </ul>
        <span v-else>{{ field.value ?? '—' }}</span>
      </template>
      <span v-else class="ek-field__state">{{ stateLabel(t, field.state) }}</span>
    </div>
    <div class="ek-field__meta">
      <span
        v-if="field.origin"
        data-origin
        :class="['ek-origin', { 'ek-origin--generated': field.origin === 'MODEL_GENERATED' }]"
      >{{ originLabel(t, field.origin) }}</span>
      <button
        v-for="index in field.evidenceCount"
        :key="index"
        type="button"
        class="ek-link-button"
        @click="emit('open', index - 1)"
      >{{ t('enterpriseKnowledge.entity.source', { n: index }) }}</button>
    </div>
  </div>
</template>
