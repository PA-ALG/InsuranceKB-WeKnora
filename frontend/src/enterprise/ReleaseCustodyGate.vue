<script setup lang="ts">
defineProps<{ managed: boolean; nativeAllowed: boolean; loading?: boolean; error?: string }>()
defineEmits<{ retry: [] }>()
</script>

<template>
  <slot v-if="nativeAllowed" />
  <span v-else-if="managed" class="release-custody-notice" role="status">该知识库由发布链管理，内容以发布版本为准</span>
  <span v-else-if="error" class="release-custody-notice" role="alert">
    {{ error }} <button type="button" @click="$emit('retry')">重试</button>
  </span>
  <span v-else-if="loading" class="release-custody-notice" role="status">正在确认知识库发布状态…</span>
</template>

<style scoped>
.release-custody-notice { margin-left: 12px; font-size: 12px; font-weight: normal; color: var(--td-text-color-secondary); }
button { cursor: pointer; color: var(--td-brand-color); }
</style>
