package interfaces

import "context"

// ConceptAgentSource830G2 is the source identity retained in an Agent result.
// It contains no source bytes and cannot be used to mint a source-viewer URL.
type ConceptAgentSource830G2 struct {
	SourceType   string `json:"source_type"`
	KnowledgeID  string `json:"knowledge_id"`
	RevisionID   string `json:"revision_id"`
	ParseAttempt int64  `json:"parse_attempt"`
	BlockID      string `json:"block_id"`
	PageNumber   int    `json:"page_number"`
	SourceHash   string `json:"source_hash"`
	ParseHash    string `json:"parse_hash"`
	QuoteHash    string `json:"quote_hash"`
}

// ConceptAgentMember830G2 is one immutable member of the turn-local release.
type ConceptAgentMember830G2 struct {
	Kind         string                    `json:"kind"`
	MemberID     string                    `json:"member_id"`
	OwnerID      string                    `json:"owner_id"`
	Title        string                    `json:"title"`
	Content      string                    `json:"content"`
	MemberDigest string                    `json:"member_digest"`
	Sources      []ConceptAgentSource830G2 `json:"sources"`
}

// ConceptAgentRelease830G2 is the single immutable release pinned for one Wiki
// KB when an Agent turn is constructed.
type ConceptAgentRelease830G2 struct {
	WikiKBID        string                    `json:"wiki_kb_id"`
	SpaceID         string                    `json:"space_id"`
	RawKBID         string                    `json:"raw_kb_id"`
	ReleaseID       string                    `json:"release_id"`
	ActivationEpoch uint64                    `json:"activation_epoch"`
	Members         []ConceptAgentMember830G2 `json:"members"`
}

// ConceptAgentTurn830G2 separates release-managed Wiki KBs from ordinary Wiki
// KBs. Absence from Releases means the existing unmanaged path remains valid.
type ConceptAgentTurn830G2 struct {
	Releases map[string]ConceptAgentRelease830G2 `json:"releases"`
}

// ConceptAgentWikiScope830G2 is the server-resolved owner identity for one
// Wiki search target. TenantID is re-read from the current KB row before the
// release authority is consulted.
type ConceptAgentWikiScope830G2 struct {
	WikiKBID string `json:"wiki_kb_id"`
	TenantID uint64 `json:"tenant_id"`
}

// ConceptAgentTurnProvider830G2 resolves every managed Wiki scope and freezes
// its current release exactly once before any Agent tool is registered.
type ConceptAgentTurnProvider830G2 interface {
	PinConceptAgentTurn830G2(
		ctx context.Context,
		wikiScopes []ConceptAgentWikiScope830G2,
	) (*ConceptAgentTurn830G2, error)
}
