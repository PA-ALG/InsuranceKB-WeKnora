<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CitationPanel from './CitationPanel.vue'
import { releaseCitationTarget } from './releaseReferences'

const props = defineProps<{ reference: Parameters<typeof releaseCitationTarget>[0]; denied?: boolean }>()
const { t } = useI18n()
const target = computed(() => releaseCitationTarget(props.reference))
</script>

<template>
  <p v-if="denied" role="alert">{{ t('chat.releaseCitationDenied') }}</p>
  <p v-else-if="!target" role="alert">{{ t('chat.releaseCitationUnavailable') }}</p>
  <CitationPanel v-else :key="JSON.stringify(target)" v-bind="target" />
</template>
