<script setup lang="ts">
import { computed, nextTick, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { reviewReasonLength, trimReviewReason } from './reviewReason'
const props = defineProps<{
  busy: boolean; blocked: boolean; group?: boolean; approveDisabled?: boolean; rejectDisabled?: boolean
  approveHint?: string; rejectHint?: string
}>()
const emit = defineEmits<{ decide: [outcome: 'approve' | 'reject', reason: string] }>()
const { t } = useI18n(), id = useId()
const reason = ref(''), writing = ref(false), rejecting = ref(false), input = ref<HTMLTextAreaElement>()
const count = computed(() => reviewReasonLength(reason.value))
const locked = computed(() => props.busy)
async function write(reject = false) {
  if (locked.value || (reject && props.rejectDisabled)) return
  writing.value = true; rejecting.value = reject
  await nextTick(); input.value?.focus()
}
function send(outcome: 'approve' | 'reject') {
  if (locked.value || count.value > 2000 || (outcome === 'approve' ? props.blocked || props.approveDisabled : count.value === 0 || props.rejectDisabled)) return
  emit('decide', outcome, trimReviewReason(reason.value) || t('enterpriseKnowledge.review.defaultReason'))
}
</script>
<template>
  <div class="ek-point-actions">
    <button v-if="!writing" type="button" class="ek-link-button" :disabled="locked" @click="write()">{{ t('enterpriseKnowledge.review.writeReason') }}</button>
    <div v-if="writing" class="ek-review-reason">
      <label :for="`${id}-reason`">{{ t(rejecting ? 'enterpriseKnowledge.review.reason' : 'enterpriseKnowledge.review.optionalReason') }}</label>
      <textarea :id="`${id}-reason`" ref="input" v-model="reason" :disabled="locked" rows="2" :aria-invalid="count > 2000 || (rejecting && count === 0)" :aria-describedby="`${id}-count`" />
      <p :id="`${id}-count`" class="ek-page__meta">{{ t('enterpriseKnowledge.review.reasonCount', { count }) }}</p>
    </div>
    <div class="ek-review-actions">
      <button type="button" class="ek-button ek-review-approve" :data-point-approve="!group ? '' : undefined" :data-unknown-approve="group ? '' : undefined"
        :disabled="locked || blocked || approveDisabled || count > 2000" :aria-describedby="approveHint" @click="send('approve')">{{ t(group ? 'enterpriseKnowledge.review.approveUnknown' : 'enterpriseKnowledge.review.approve') }}</button>
      <button type="button" class="ek-button" :data-point-reject="!group ? '' : undefined" :data-unknown-reject="group ? '' : undefined"
        :disabled="locked || rejectDisabled" :aria-describedby="rejectHint" @click="write(true)">{{ t(group ? 'enterpriseKnowledge.review.rejectUnknown' : 'enterpriseKnowledge.review.reject') }}</button>
      <button v-if="rejecting" type="button" class="ek-button" data-point-confirm-reject :disabled="locked || rejectDisabled || !count || count > 2000" :aria-describedby="rejectHint"
        @click="send('reject')">{{ t('enterpriseKnowledge.review.confirmReject') }}</button>
    </div>
  </div>
</template>
