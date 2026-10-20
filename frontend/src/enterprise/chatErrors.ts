const errorKeys = {
  RELEASE_MANAGED_KB: 'managedKb',
  MANAGED_KB_CLASSIFICATION_UNAVAILABLE: 'classificationUnavailable',
  RELEASE_SOURCES_UNAVAILABLE: 'sourcesUnavailable',
  RELEASE_NOT_FOUND: 'releaseNotFound',
}

export function enterpriseChatError(raw: string, t: (key: string) => string): string | null {
  for (const [code, key] of Object.entries(errorKeys)) {
    if (raw === code || raw.startsWith(`${code}:`)) return t(`enterpriseKnowledge.chatErrors.${key}`)
  }
  return null
}
