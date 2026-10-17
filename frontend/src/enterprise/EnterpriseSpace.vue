<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { EnterpriseError, readRelease, type Release } from './enterpriseApi'
import { entitySummaries } from './releaseView'

const props = defineProps<{ spaceId: string }>()
const { t } = useI18n()
const state = ref<'loading' | 'failed' | 'unpublished' | 'ready'>('loading')
const release = ref<Release | null>(null)
const summaries = computed(() => (release.value ? entitySummaries(release.value) : []))
let generation = 0

async function load() {
  const current = ++generation
  state.value = 'loading'
  try {
    const active = await readRelease(props.spaceId)
    if (current !== generation) return
    release.value = active
    state.value = 'ready'
  } catch (error) {
    if (current !== generation) return
    // A Space that has never published is empty, not broken.
    state.value = error instanceof EnterpriseError && error.code === 'RELEASE_NOT_FOUND' ? 'unpublished' : 'failed'
  }
}

watch(() => props.spaceId, load, { immediate: true })
</script>

<template>
  <main class="ek-page">
    <h1 class="ek-page__title">{{ spaceId }}</h1>
    <p v-if="state === 'loading'" role="status" class="ek-status">{{ t('enterpriseKnowledge.loading') }}</p>
    <div v-else-if="state === 'failed'" role="alert" class="ek-alert">
      <span>{{ t('enterpriseKnowledge.space.failed') }}</span>
      <button type="button" class="ek-button" @click="load">{{ t('enterpriseKnowledge.retry') }}</button>
    </div>
    <p v-else-if="state === 'unpublished'" class="ek-empty">{{ t('enterpriseKnowledge.space.noRelease') }}</p>
    <template v-else-if="release">
      <p class="ek-page__meta">{{ t('enterpriseKnowledge.space.version', { epoch: release.epoch }) }}</p>
      <p v-if="summaries.length === 0" class="ek-empty">{{ t('enterpriseKnowledge.space.empty') }}</p>
      <ul v-else class="ek-cards">
        <li v-for="entry in summaries" :key="entry.entityId" class="ek-card">
          <RouterLink
            class="ek-card__link"
            :to="{ name: 'enterpriseEntity', params: { spaceId, entityId: entry.entityId }, query: { release: release.id } }"
          >
            <span class="ek-card__name">{{ entry.name }}</span>
            <span class="ek-card__meta">{{ t('enterpriseKnowledge.space.fieldCount', { count: entry.fieldCount }) }}</span>
          </RouterLink>
        </li>
      </ul>
    </template>
  </main>
</template>

<style src="./enterprisePage.css"></style>
