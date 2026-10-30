// Upstream's ru-RU bundle with our strings merged in, as the app sees it at
// runtime. Specs that render enterprise UI import this, not the upstream file.
import base from '../../../i18n/locales/ru-RU.ts'
import { mergeMessages } from '../merge.ts'
import extra from '../messages/ru-RU.ts'

export default mergeMessages(base, extra)
