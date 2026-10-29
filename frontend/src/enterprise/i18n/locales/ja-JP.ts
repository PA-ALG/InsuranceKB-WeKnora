// Upstream's ja-JP bundle with our strings merged in, as the app sees it at
// runtime. Specs that render enterprise UI import this, not the upstream file.
import base from '../../../i18n/locales/ja-JP.ts'
import { mergeMessages } from '../merge.ts'
import extra from '../messages/ja-JP.ts'

export default mergeMessages(base, extra)
