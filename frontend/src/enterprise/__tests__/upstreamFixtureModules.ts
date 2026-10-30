// Our modules as upstream's whitebox fixture (src/test-utils/vueFixture.ts)
// resolves them when it evaluates an upstream file we patched with one call
// line. Pure modules are real; network-backed ones answer as for a knowledge
// base outside the release chain, which is the case upstream's tests cover.
import { computed, ref } from 'vue'
import * as chatErrors from '../chatErrors.ts'

export const enterpriseFixtureModules: Record<string, unknown> = {
  '@/enterprise/chatErrors': chatErrors,
  '@/enterprise/useReleaseCustody': {
    useReleaseCustody: () => ({
      isManaged: computed(() => false),
      nativeWikiAllowed: computed(() => true),
      loading: ref(false),
      error: ref(''),
      retry: async () => {},
    }),
  },
}
