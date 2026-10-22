import { getActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'

// Whether to offer the expert edit form (S9b Spec §2.2). The server decides every edit (S9a
// checks the tenant role on the route and again in the handler); this only hides a form the
// server would refuse. Without a store the role is unknown, so nothing is offered.
export function canOfferExpertEdit(): boolean {
  return getActivePinia() !== undefined && useAuthStore().hasRole('admin')
}
