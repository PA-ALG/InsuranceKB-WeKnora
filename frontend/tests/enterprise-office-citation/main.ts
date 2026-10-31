import { createApp } from 'vue'
import { createI18n } from 'vue-i18n'
import TDesign from 'tdesign-vue-next'
import 'tdesign-vue-next/dist/tdesign.css'
import '../../src/assets/theme/theme.css'
import zhCN from '../../src/enterprise/i18n/locales/zh-CN'
import { installTDesignIconOfflineGuard } from '../../src/utils/tdesign-icon-offline'
import Harness from './Harness.vue'

// As in the app: no icon font from the CDN, so any request leaving the page is the file's doing.
installTDesignIconOfflineGuard()

createApp(Harness)
  .use(TDesign)
  .use(createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } }))
  .mount('#app')
