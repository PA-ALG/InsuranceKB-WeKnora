package release

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// Service validates and stores candidates without interpreting member payloads.
type Service struct {
	store      Store
	evidence   EvidenceResolver
	publisher  Publisher
	references ReferenceReader
	queue      QueueStore
	retirer    Retirer
	verifier   EvidenceVerifier
	schema     *jsonschema.Schema
	// evidenceSchema is optional: without it, payload evidence fails closed as unverifiable.
	evidenceSchema *jsonschema.Schema
	schemaErr      error
}

// NewService compiles the supplied schema once. Invalid or absent schema
// configuration fails closed on Receive, without filesystem or network access.
// Publishing (decisions, activation, release reads) needs WithPublisher.
func NewService(store Store, evidence EvidenceResolver, schemas map[string][]byte, options ...Option) *Service {
	schema, evidenceSchema, err := compileSchemas(schemas)
	s := &Service{
		store: store, evidence: evidence, schema: schema, evidenceSchema: evidenceSchema, schemaErr: err,
	}
	s.queue, _ = store.(QueueStore)
	for _, option := range options {
		option(s)
	}
	return s
}

// Receive validates the complete submission before asking the Store to persist it.
func (s *Service) Receive(ctx context.Context, p Principal, spaceID string, raw []byte) (Candidate, error) {
	if err := checkAccess(p, spaceID); err != nil {
		return Candidate{}, err
	}
	if err := ctx.Err(); err != nil {
		return Candidate{}, err
	}
	ctx = context.WithValue(ctx, scopeKey{}, newScope(p, spaceID))
	b, digest, err := s.validate(ctx, raw)
	if err != nil {
		return Candidate{}, err
	}
	if s.store == nil {
		return Candidate{}, errors.New("candidate store unavailable")
	}
	if err := ctx.Err(); err != nil {
		return Candidate{}, err
	}
	c, err := s.store.CreateCandidate(ctx, Candidate{
		SpaceID: spaceID, TenantID: p.TenantID, ContractVersion: b.ContractVersion,
		BundleDigest: digest, BaseReleaseID: b.BaseReleaseID,
	}, b)
	if err != nil {
		return Candidate{}, fmt.Errorf("create candidate: %w", err)
	}
	if err := checkCandidateAccess(c, p, spaceID); err != nil {
		return Candidate{}, err
	}
	if c.ID == "" || c.BundleDigest != digest || c.BaseReleaseID != b.BaseReleaseID ||
		c.ContractVersion != b.ContractVersion {
		return Candidate{}, errors.New("candidate store returned an inconsistent record")
	}
	return c, nil
}

func checkAccess(p Principal, spaceID string) error {
	if p.TenantID == 0 || strings.TrimSpace(p.Subject) == "" || strings.TrimSpace(spaceID) == "" {
		return &Error{Code: ErrorReleaseAccessDenied, Detail: "tenant, subject and Space are required"}
	}
	return nil
}

func checkCandidateAccess(c Candidate, p Principal, spaceID string) error {
	if c.TenantID != p.TenantID || c.SpaceID != spaceID {
		return &Error{Code: ErrorReleaseAccessDenied, Detail: "candidate is outside the request scope"}
	}
	return nil
}

func invalid(detail string) error { return &Error{Code: ErrorCandidateInvalid, Detail: detail} }
