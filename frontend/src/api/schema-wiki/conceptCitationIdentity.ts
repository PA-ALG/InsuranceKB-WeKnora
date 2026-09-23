// The citation occurrence identity is shared with the serving API and preview verifier.
export async function conceptSHA256830G2(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', Uint8Array.from(bytes).buffer)
  return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('')
}
export async function conceptCitationID(candidate: string, member: string, evidence: Record<string, unknown>): Promise<string> {
  const raw = JSON.stringify([candidate, member, evidence.revision_id, evidence.block_id,
    evidence.page_number, evidence.start, evidence.end, evidence.quote_hash])
    .replace(/[<>&\u2028\u2029]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'))
  return 'citation-' + (await conceptSHA256830G2(new TextEncoder().encode(raw))).slice(0, 24)
}
