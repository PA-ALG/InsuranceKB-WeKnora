// Upstream's zh-CN bundle with our strings merged in, as the app sees it at
// runtime. Specs that render enterprise UI import this, not the upstream file.
import base from '../../../i18n/locales/zh-CN.ts'
import { mergeMessages } from '../merge.ts'
import extra from '../messages/zh-CN.ts'

export default mergeMessages(base, extra)
