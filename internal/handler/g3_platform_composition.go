package handler

import (
	"bytes"
	"context"
	"time"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
)

// ConfiguredG3PlatformSystemOptions adds only the isolated system trust domain.
// Human review and PublishAuthorizationV0 keep their existing verifiers.
func ConfiguredG3PlatformSystemOptions(cfg *config.Config, now func() time.Time) (service.WikiReleaseServiceOptions, error) {
	if now == nil {
		now = time.Now
	}
	initial, err := config.DecodeG3PlatformProcessing(cfg, now())
	if err != nil {
		return service.WikiReleaseServiceOptions{}, err
	}
	if initial == nil {
		return service.WikiReleaseServiceOptions{}, nil
	}
	keys := initial.SystemDecisionKeys()
	provider := service.SystemAutomationPolicyProviderFunc(func(ctx context.Context, p types.WikiReleasePrincipal, scope types.WikiReleaseScope) (*service.SystemAutomationPolicy, error) {
		if ctx == nil || ctx.Err() != nil {
			return nil, service.ErrWikiReleaseInvalidAuthorization
		}
		current, err := config.DecodeG3PlatformProcessing(cfg, now())
		if err != nil || current == nil || current.Scope != scope || p.ID != current.Settings.MachinePrincipalID || p.TenantID != scope.TenantID || p.SpaceID != scope.SpaceID {
			return nil, service.ErrWikiReleaseInvalidAuthorization
		}
		// A verifier is frozen at startup. Configuration drift must never authorize
		// a receipt with a removed/replaced key until the matching verifier restarts.
		currentKeys := current.SystemDecisionKeys()
		if len(keys) != len(currentKeys) {
			return nil, service.ErrWikiReleaseInvalidAuthorization
		}
		for id, key := range keys {
			if !bytes.Equal(key, currentKeys[id]) {
				return nil, service.ErrWikiReleaseInvalidAuthorization
			}
		}
		c := current.Settings
		policy := &service.SystemAutomationPolicy{PolicyID: c.PolicyID, Version: c.PolicyVersion, Mode: c.Mode, Enabled: c.Enabled, PrincipalID: c.MachinePrincipalID, APIKeyID: c.APIKeyID, WikiReleaseScope: scope, Capabilities: append([]string(nil), c.Capabilities...), NotBefore: c.NotBefore, ExpiresAt: c.ExpiresAt, SignerKeyID: c.SystemDecisionKeyID}
		policy.Digest, err = service.SystemAutomationPolicyDigest(policy)
		if err != nil {
			return nil, service.ErrWikiReleaseInvalidAuthorization
		}
		return policy, nil
	})
	return service.WikiReleaseServiceOptions{SystemPolicyProvider: provider, SystemDecisionVerifier: service.NewEd25519SystemPolicyDecisionVerifier(keys)}, nil
}

// NewConfiguredG3PlatformHandlers composes the existing source custody and
// system-release services. A disabled deployment exposes no machine routes.
func NewConfiguredG3PlatformHandlers(cfg *config.Config, knowledge service.G3PlatformMachineKnowledgeRepository, revisions *service.KnowledgeRevisionSourceService, sources *service.ConceptSourceAuthorityService830G2, spans repository.KnowledgeSpanRepository, access *WikiReleaseHandler, schemas *service.SchemaWikiService, releases *service.WikiReleaseService) (*G3PlatformSnapshotsHandler, *G3PlatformReleaseHandler, error) {
	runtime, err := config.DecodeG3PlatformProcessing(cfg, time.Now())
	if err != nil {
		return nil, nil, err
	}
	if runtime == nil {
		return nil, nil, nil
	}
	if knowledge == nil || revisions == nil || sources == nil || spans == nil || access == nil || schemas == nil || releases == nil {
		return nil, nil, service.ErrG3PlatformSnapshotUnavailable
	}
	signer, err := service.NewEd25519G3PlatformSnapshotSigner(runtime.Settings.SourceSnapshotSigningKey.KeyID, runtime.SnapshotSigningKey())
	if err != nil {
		return nil, nil, err
	}
	machine := service.NewG3PlatformMachineAccessService(knowledge, releases, service.G3PlatformMachineAccessBinding{PrincipalStorageID: runtime.Settings.MachinePrincipalID, APIKeyID: runtime.Settings.APIKeyID, Scope: runtime.Scope})
	sourceSnapshots := service.NewG3PlatformSourceSnapshotService(
		revisions, sources, service.NewKnowledgeModelDispatchJournal(spans), machine, signer,
	)
	baseSnapshots := service.NewG3PlatformBaseSnapshotService(releases, machine, signer)
	return NewG3PlatformSnapshotsHandler(access, machine, sourceSnapshots, baseSnapshots), NewG3PlatformReleaseHandler(access, schemas, releases), nil
}
