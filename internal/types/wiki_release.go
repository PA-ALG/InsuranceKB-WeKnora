package types

import (
	"encoding/json"
	"time"
)

// PublishAuthorizationV0 is the frozen, experimental S0-R authorization
// envelope. It is not a production protocol.
type PublishAuthorizationV0 struct {
	Version                 string `json:"version"`
	Action                  string `json:"action"`
	PreparationID           string `json:"preparation_id"`
	CandidateDigest         string `json:"candidate_digest"`
	ManifestDigest          string `json:"manifest_digest"`
	ReadyReceiptDigest      string `json:"ready_receipt_digest"`
	ReviewDecisionDigest    string `json:"review_decision_digest"`
	ReviewPolicyID          string `json:"review_policy_id"`
	TenantID                uint64 `json:"tenant_id"`
	SpaceID                 string `json:"space_id"`
	RawKBID                 string `json:"raw_kb_id"`
	WikiKBID                string `json:"wiki_kb_id"`
	ExpectedReleaseID       string `json:"expected_release_id"`
	ExpectedActivationEpoch uint64 `json:"expected_activation_epoch"`
	ExpiresAt               int64  `json:"expires_at"`
	Nonce                   string `json:"nonce"`
	SignerKeyID             string `json:"signer_key_id"`
	Signature               string `json:"signature"`
}

// WikiReleaseScope is the exact experimental release boundary.
type WikiReleaseScope struct {
	TenantID uint64 `json:"tenant_id" gorm:"column:tenant_id;not null"`
	SpaceID  string `json:"space_id" gorm:"column:space_id;not null"`
	RawKBID  string `json:"raw_kb_id" gorm:"column:raw_kb_id;not null"`
	WikiKBID string `json:"wiki_kb_id" gorm:"column:wiki_kb_id;not null"`
}

// WikiReleasePrincipal is the fail-closed identity presented to the
// experimental release service.
type WikiReleasePrincipal struct {
	ID                     string   `json:"id"`
	TenantID               uint64   `json:"tenant_id"`
	SpaceID                string   `json:"space_id"`
	APIKeyKnowledgeBaseIDs []string `json:"api_key_knowledge_base_ids,omitempty"`
}

// WikiReleaseMemberSnapshot is the canonical immutable member captured by a
// Ready preparation.
type WikiReleaseMemberSnapshot struct {
	Kind         string          `json:"kind"`
	LogicalSlug  string          `json:"logical_slug"`
	RevisionID   string          `json:"revision_id"`
	MemberDigest string          `json:"member_digest"`
	Title        string          `json:"title"`
	Content      string          `json:"content"`
	Payload      json.RawMessage `json:"payload"`
}

const (
	// WikiReleasePreparationReady is the only activatable preparation state.
	WikiReleasePreparationReady = "ready"
)

// WikiReleasePreparation stores the complete canonical manifest and immutable
// member snapshot before activation.
type WikiReleasePreparation struct {
	ID string `json:"preparation_id" gorm:"column:preparation_id;primaryKey"`
	WikiReleaseScope
	CandidateDigest         string                      `json:"candidate_digest" gorm:"column:candidate_digest;not null"`
	ManifestDigest          string                      `json:"manifest_digest" gorm:"column:manifest_digest;not null"`
	ReadyReceiptDigest      string                      `json:"ready_receipt_digest" gorm:"column:ready_receipt_digest;not null"`
	ReviewDecisionDigest    string                      `json:"review_decision_digest" gorm:"column:review_decision_digest;not null"`
	ReviewPolicyID          string                      `json:"review_policy_id" gorm:"column:review_policy_id;not null"`
	ExpectedReleaseID       string                      `json:"expected_release_id" gorm:"column:expected_release_id;not null"`
	ExpectedActivationEpoch uint64                      `json:"expected_activation_epoch" gorm:"column:expected_activation_epoch;not null"`
	Status                  string                      `json:"status" gorm:"column:status;not null"`
	Manifest                json.RawMessage             `json:"manifest" gorm:"column:manifest;type:jsonb;serializer:json;not null"`
	Members                 []WikiReleaseMemberSnapshot `json:"members" gorm:"column:members;type:jsonb;serializer:json;not null"`
	PreparationDigest       string                      `json:"preparation_digest" gorm:"column:preparation_digest;not null"`
	CreatedAt               time.Time                   `json:"created_at" gorm:"column:created_at;not null"`
}

// TableName freezes the experimental migration identity.
func (WikiReleasePreparation) TableName() string { return "wiki_release_preparations" }

// WikiRelease is an immutable activated release.
type WikiRelease struct {
	ID string `json:"release_id" gorm:"column:release_id;primaryKey"`
	WikiReleaseScope
	CandidateDigest     string    `json:"candidate_digest" gorm:"column:candidate_digest;not null"`
	ManifestDigest      string    `json:"manifest_digest" gorm:"column:manifest_digest;not null"`
	BaseReleaseID       string    `json:"base_release_id" gorm:"column:base_release_id;not null"`
	BaseActivationEpoch uint64    `json:"base_activation_epoch" gorm:"column:base_activation_epoch;not null"`
	PreparationID       string    `json:"preparation_id" gorm:"column:preparation_id;not null"`
	CreatedAt           time.Time `json:"created_at" gorm:"column:created_at;not null"`
	ActivatedAt         time.Time `json:"activated_at" gorm:"column:activated_at;not null"`
}

// TableName freezes the experimental migration identity.
func (WikiRelease) TableName() string { return "wiki_releases" }

// WikiReleaseMember is an immutable materialized release member.
type WikiReleaseMember struct {
	ID           string          `json:"id" gorm:"column:id;primaryKey"`
	ReleaseID    string          `json:"release_id" gorm:"column:release_id;not null"`
	Kind         string          `json:"kind" gorm:"column:kind;not null"`
	LogicalSlug  string          `json:"logical_slug" gorm:"column:logical_slug;not null"`
	RevisionID   string          `json:"revision_id" gorm:"column:revision_id;not null"`
	MemberDigest string          `json:"member_digest" gorm:"column:member_digest;not null"`
	Title        string          `json:"title" gorm:"column:title;not null"`
	Content      string          `json:"content" gorm:"column:content;not null"`
	Payload      json.RawMessage `json:"payload" gorm:"column:payload;type:jsonb;serializer:json;not null"`
}

// TableName freezes the experimental migration identity.
func (WikiReleaseMember) TableName() string { return "wiki_release_members" }

// Snapshot returns the immutable read representation.
func (member WikiReleaseMember) Snapshot() WikiReleaseMemberSnapshot {
	return WikiReleaseMemberSnapshot{
		Kind:         member.Kind,
		LogicalSlug:  member.LogicalSlug,
		RevisionID:   member.RevisionID,
		MemberDigest: member.MemberDigest,
		Title:        member.Title,
		Content:      member.Content,
		Payload:      append(json.RawMessage(nil), member.Payload...),
	}
}

// WikiReleaseHead is the sole serving head for one release scope.
type WikiReleaseHead struct {
	ID string `json:"id" gorm:"column:id;primaryKey"`
	WikiReleaseScope
	ActiveReleaseID string    `json:"active_release_id" gorm:"column:active_release_id;not null"`
	ActivationEpoch uint64    `json:"activation_epoch" gorm:"column:activation_epoch;not null"`
	UpdatedAt       time.Time `json:"updated_at" gorm:"column:updated_at;not null"`
}

// TableName freezes the experimental migration identity.
func (WikiReleaseHead) TableName() string { return "wiki_release_heads" }

// WikiReleaseReceipt is the immutable idempotency and activation receipt.
type WikiReleaseReceipt struct {
	ID string `json:"receipt_id" gorm:"column:receipt_id;primaryKey"`
	WikiReleaseScope
	Nonce               string    `json:"nonce" gorm:"column:nonce;not null"`
	AuthorizationDigest string    `json:"authorization_digest" gorm:"column:authorization_digest;not null"`
	PreviousReleaseID   string    `json:"previous_release_id" gorm:"column:previous_release_id;not null"`
	ReleaseID           string    `json:"release_id" gorm:"column:release_id;not null"`
	ActivationEpoch     uint64    `json:"activation_epoch" gorm:"column:activation_epoch;not null"`
	ActivatedBy         string    `json:"activated_by" gorm:"column:activated_by;not null"`
	CreatedAt           time.Time `json:"created_at" gorm:"column:created_at;not null"`
}

// TableName freezes the experimental migration identity.
func (WikiReleaseReceipt) TableName() string { return "wiki_release_receipts" }

// WikiReleaseCurrent pins one request to one immutable release.
type WikiReleaseCurrent struct {
	ReleaseID       string `json:"release_id"`
	ActivationEpoch uint64 `json:"activation_epoch"`
}

// WikiReleaseStateCount supports bounded zero-half-write falsification.
type WikiReleaseStateCount struct {
	Preparations int64
	Releases     int64
	Members      int64
	Heads        int64
	Receipts     int64
}
