// Go strings.TrimSpace uses Unicode White_Space, unlike JavaScript trim (NEL/BOM differ).
export const trimReviewReason = (value: string) => value.replace(/^\p{White_Space}+|\p{White_Space}+$/gu, '')
export const reviewReasonLength = (value: string) => Array.from(trimReviewReason(value)).length
