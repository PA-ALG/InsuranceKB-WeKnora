export interface GoldenReviewerPresentation {
  readonly sourceReview: {
    readonly status: 'COMPLETED'
    readonly reviewedBy: 'linyao'
    readonly reviewedAtLabel: 'UNKNOWN'
    readonly annotatorModelId: 'claude-fable-5'
    readonly attestedBy: 'workspace-owner-houjing'
  }
  readonly mapping: {
    readonly status: 'COMPLETE_67'
    readonly closedCount: number
    readonly residualCount: number
    readonly orderedResidualFieldIds: ReadonlyArray<string>
  }
  readonly admission: {
    readonly status: 'BLOCKED_RECEIPT_UNVERIFIED'
    readonly readyToSignStatus: 'READY_TO_SIGN'
    readonly receiptStatus: 'UNVERIFIED'
    readonly blockingReasonCodes: ReadonlyArray<'GOLDEN_APPROVAL_RECEIPT_UNVERIFIED'>
  }
}
