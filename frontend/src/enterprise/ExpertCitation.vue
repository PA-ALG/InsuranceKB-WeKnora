<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ExpertCitation } from './enterpriseApi'
import { expertRoleLabel, stateLabel } from './fieldLabels'

// The revision record an expert-revised field cites (S9b Spec §2.5): who, when, from what to
// what and why. The record is the source itself, so no page or file is opened.
const props = defineProps<{ citation: ExpertCitation }>()
const { t } = useI18n()

const ACTOR_PREFIX = 'web_user:'
const actor = computed(() => props.citation.actor.startsWith(ACTOR_PREFIX)
  ? props.citation.actor.slice(ACTOR_PREFIX.length) : props.citation.actor)

function localMinute(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`
}

function shown(side: { state: string; value: unknown }): string {
  if (side.state !== 'present') return stateLabel(t, side.state)
  const value = side.value
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(item => String(item)).join('；')
  return value === null || value === undefined ? '—' : JSON.stringify(value)
}

const rows = computed(() => [
  { key: 'actor', label: t('enterpriseKnowledge.expert.actor'), text: actor.value },
  { key: 'role', label: t('enterpriseKnowledge.expert.role'), text: expertRoleLabel(t, props.citation.role) },
  { key: 'time', label: t('enterpriseKnowledge.expert.time'), text: localMinute(props.citation.recorded_at) },
  { key: 'before', label: t('enterpriseKnowledge.expert.before'), text: shown(props.citation.before) },
  { key: 'after', label: t('enterpriseKnowledge.expert.after'), text: shown(props.citation.after) },
  { key: 'reason', label: t('enterpriseKnowledge.expert.reason'), text: props.citation.reason },
])
</script>

<template>
  <section data-expert-revision class="ek-expert-record" :aria-label="t('enterpriseKnowledge.expert.record')">
    <h3 class="ek-expert-record__title">{{ t('enterpriseKnowledge.expert.record') }}</h3>
    <dl class="ek-expert-record__rows">
      <template v-for="row in rows" :key="row.key">
        <dt>{{ row.label }}</dt>
        <dd :data-record="row.key">{{ row.text }}</dd>
      </template>
    </dl>
  </section>
</template>

<style src="./expertEdit.css"></style>
