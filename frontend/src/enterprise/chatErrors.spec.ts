// S6d-2 acceptance (protected, written by Claude): enterprise refusals in chat read as guidance,
// not raw codes; other errors are left alone (Spec docs/design/slices/S6d-2-延伸阅读与知识库选择体验.md §2).
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import { enterpriseChatError } from './chatErrors'

const { t } = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } }).global

describe('enterprise errors in chat', () => {
  it('explains each enterprise refusal by its code', () => {
    expect(enterpriseChatError('RELEASE_MANAGED_KB: 该知识库由发布链管理，请通过发布版本读取', t))
      .toBe('这个知识库由发布版本管理，不能直接检索。请在企业知识中选择对应 Space 的原始材料库或 Wiki 库提问，或改用智能推理模式。')
    expect(enterpriseChatError('MANAGED_KB_CLASSIFICATION_UNAVAILABLE: lookup failed', t))
      .toBe('暂时无法确认这个知识库是否由发布版本管理，已停止回答，请稍后重试。')
    expect(enterpriseChatError('RELEASE_SOURCES_UNAVAILABLE', t))
      .toBe('当前发布版本固定的原始材料暂时不可检索，请稍后重试或改选 Wiki 库。')
    expect(enterpriseChatError('RELEASE_NOT_FOUND: no active release', t))
      .toBe('这个企业知识 Space 还没有发布版本，暂时不能问答。')
  })

  it('leaves other errors and look-alike codes unchanged', () => {
    expect(enterpriseChatError('network timeout', t)).toBeNull()
    expect(enterpriseChatError('RELEASE_MANAGED_KBX: other', t)).toBeNull()
    expect(enterpriseChatError('error: RELEASE_MANAGED_KB: nested', t)).toBeNull()
    expect(enterpriseChatError('', t)).toBeNull()
  })
})
