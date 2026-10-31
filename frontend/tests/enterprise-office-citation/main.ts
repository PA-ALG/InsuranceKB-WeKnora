import { createApp } from 'vue'
import { createI18n } from 'vue-i18n'
import TDesign from 'tdesign-vue-next'
import 'tdesign-vue-next/dist/tdesign.css'
import '../../src/assets/theme/theme.css'
import zhCN from '../../src/enterprise/i18n/locales/zh-CN'
import Harness from './Harness.vue'

createApp(Harness)
  .use(TDesign)
  .use(createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } }))
  .mount('#app')
