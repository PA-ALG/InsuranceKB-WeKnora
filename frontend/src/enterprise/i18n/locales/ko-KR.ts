// Upstream's ko-KR bundle with our strings merged in, as the app sees it at
// runtime. Specs that render enterprise UI import this, not the upstream file.
import base from '../../../i18n/locales/ko-KR.ts'
import { mergeMessages } from '../merge.ts'
import extra from '../messages/ko-KR.ts'

export default mergeMessages(base, extra)
