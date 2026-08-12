package service

import (
	"context"

	"github.com/Tencent/WeKnora/internal/types"
)

// SchemaWikiGoldenSuccessorStatusProvider is a deployment-composed read-only
// authority. HTTP callers cannot supply its bytes or replace it per request.
type SchemaWikiGoldenSuccessorStatusProvider interface {
	GoldenSuccessorStatus(context.Context) (*types.SchemaWikiGoldenSuccessorStatusV1, error)
}

type canonicalSchemaWikiGoldenSuccessorStatusProvider struct {
	canonical []byte
}

// NewCanonicalSchemaWikiGoldenSuccessorStatusProvider freezes one exact closed
// canonical artifact. Empty input is the secure unconfigured state.
func NewCanonicalSchemaWikiGoldenSuccessorStatusProvider(
	canonical []byte,
) (SchemaWikiGoldenSuccessorStatusProvider, error) {
	if len(canonical) == 0 {
		return nil, nil
	}
	if _, err := types.ParseSchemaWikiGoldenSuccessorStatusV1(canonical); err != nil {
		return nil, err
	}
	return &canonicalSchemaWikiGoldenSuccessorStatusProvider{
		canonical: append([]byte(nil), canonical...),
	}, nil
}

func (p *canonicalSchemaWikiGoldenSuccessorStatusProvider) GoldenSuccessorStatus(
	context.Context,
) (*types.SchemaWikiGoldenSuccessorStatusV1, error) {
	if p == nil || len(p.canonical) == 0 {
		return nil, ErrNoGoldenSuccessorStatus
	}
	status, err := types.ParseSchemaWikiGoldenSuccessorStatusV1(p.canonical)
	if err != nil {
		return nil, ErrNoGoldenSuccessorStatus
	}
	return &status, nil
}

// ReadSchemaWikiGoldenSuccessorStatus returns the complete67 source-coverage
// status that remains blocked only by receipt verification. It has no
// preparation, Draft, Head or serving side effect.
func (s *SchemaWikiService) ReadSchemaWikiGoldenSuccessorStatus(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
) (*types.SchemaWikiGoldenSuccessorStatusV1, error) {
	if err := requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
		return nil, err
	}
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrNoGoldenSuccessorStatus
	}
	if err := s.releaseAuthority.verifyAccess(
		ctx, principal, scope, "read-golden-successor-status",
	); err != nil {
		return nil, err
	}
	if s.goldenSuccessorStatus == nil {
		return nil, ErrNoGoldenSuccessorStatus
	}
	status, err := s.goldenSuccessorStatus.GoldenSuccessorStatus(ctx)
	if err != nil || status == nil ||
		types.ValidateSchemaWikiGoldenSuccessorStatusV1(*status) != nil ||
		status.TenantID != scope.TenantID || status.SpaceID != scope.SpaceID ||
		status.RawKBID != scope.RawKBID || status.WikiKBID != scope.WikiKBID {
		return nil, ErrNoGoldenSuccessorStatus
	}
	copy := *status
	copy.ResidualFieldIDs = append([]string{}, status.ResidualFieldIDs...)
	return &copy, nil
}
