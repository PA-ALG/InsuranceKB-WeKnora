<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Release } from './enterpriseApi'
import { businessDay, versionInfo, type Lifecycle } from './productVersions'

// PV-4b: a product version's sale status, sale period, family and supersedes links, all read from
// the release the page shows; links stay in that release. Nothing renders without version data.
const props = defineProps<{ release: Release; spaceId: string; entityId: string }>()
const { t } = useI18n()
const info = computed(() => versionInfo(props.release, props.entityId, businessDay(new Date())))
const shown = computed(() => !!(info.value.lifecycle || info.value.family || info.value.predecessors.length || info.value.successors.length))
const status = computed(() => {
  const { status, lifecycle } = info.value
  if (!status) return ''
  return status === 'on_sale' && !lifecycle?.sale_end && lifecycle?.basis_date
    ? t('enterpriseKnowledge.version.onSaleAsOf', { date: lifecycle.basis_date })
    : t(`enterpriseKnowledge.version.status.${status}`)
})
function period(lifecycle: Lifecycle | null) {
  const start = lifecycle?.sale_start, end = lifecycle?.sale_end
  if (start && end) return t('enterpriseKnowledge.version.periodRange', { start, end })
  if (start) return t('enterpriseKnowledge.version.periodFrom', { start })
  if (end) return t('enterpriseKnowledge.version.periodUntil', { end })
  return ''
}
const links = computed(() => [
  { key: 'predecessors', marker: 'data-version-predecessor', entries: info.value.predecessors },
  { key: 'successors', marker: 'data-version-successor', entries: info.value.successors },
].filter(group => group.entries.length))
const target = (entityId: string) => ({ name: 'enterpriseEntity', params: { spaceId: props.spaceId, entityId }, query: { release: props.release.id } })
</script>

<template>
  <section v-if="shown" class="ek-version" data-version-meta :aria-label="t('enterpriseKnowledge.version.title')">
    <dl class="ek-version__facts">
      <div v-if="info.status">
        <dt class="ek-sr-only">{{ t('enterpriseKnowledge.version.title') }}</dt>
        <dd><span class="ek-sale-status" :data-sale-status="info.status">{{ status }}</span></dd>
      </div>
      <div v-if="period(info.lifecycle)" data-version-period>
        <dt>{{ t('enterpriseKnowledge.version.period') }}</dt><dd>{{ period(info.lifecycle) }}</dd>
      </div>
      <div v-if="info.family" data-version-family>
        <dt>{{ t('enterpriseKnowledge.version.family') }}</dt><dd>{{ info.family.title }}</dd>
      </div>
      <div v-for="group in links" :key="group.key">
        <dt>{{ t(`enterpriseKnowledge.version.${group.key}`) }}</dt>
        <dd>
          <span v-for="link in group.entries" :key="link.entityId" class="ek-version__link" v-bind="{ [group.marker]: '' }">
            <RouterLink :to="target(link.entityId)">{{ link.name }}</RouterLink>
            <small v-if="period(link.lifecycle)">{{ period(link.lifecycle) }}</small>
          </span>
        </dd>
      </div>
    </dl>
  </section>
</template>

<style src="./productVersions.css"></style>
