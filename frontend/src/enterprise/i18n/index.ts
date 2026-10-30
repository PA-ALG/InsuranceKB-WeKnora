// Enterprise UI strings live outside upstream's locale files: each upgrade takes
// upstream's bundles unchanged and this module deep-merges our keys on top.
import { mergeMessages } from './merge.ts'
import enUS from './messages/en-US.ts'
import jaJP from './messages/ja-JP.ts'
import koKR from './messages/ko-KR.ts'
import ruRU from './messages/ru-RU.ts'
import zhCN from './messages/zh-CN.ts'

// zh-TW has no enterprise translation yet; the Simplified Chinese strings keep
// its key set equal to the other bundles (upstream's locale audit requires it).
const ENTERPRISE_MESSAGES: Record<string, object> = {
  'en-US': enUS,
  'ja-JP': jaJP,
  'ko-KR': koKR,
  'ru-RU': ruRU,
  'zh-CN': zhCN,
  'zh-TW': zhCN,
}

export function withEnterpriseMessages<T extends Record<string, object>>(bundles: T): T {
  const merged: Record<string, object> = {}
  for (const [locale, bundle] of Object.entries(bundles)) {
    const extra = ENTERPRISE_MESSAGES[locale]
    merged[locale] = extra ? mergeMessages(bundle, extra) : bundle
  }
  return merged as T
}
