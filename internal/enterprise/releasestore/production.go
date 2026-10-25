package releasestore

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"go.uber.org/dig"
	"gorm.io/gorm"

	appservice "github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	publishedknowledge "github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

// Deployment configuration of enterprise publishing (S4c-2a Spec §3.2–§3.3).
const (
	// SpacesEnv holds the JSON list parsed by ParseSpaces; unset disables publishing.
	SpacesEnv = "ENTERPRISE_SPACES"
	// ContractsDirEnv points at the repository's contracts/ directory when the
	// process does not run from the repository root (the app image ships no copy).
	ContractsDirEnv = "ENTERPRISE_CONTRACTS_DIR"

	defaultContractsDir = "contracts"
	bundleSchemaFile    = "candidate_bundle.schema.json"
	evidenceSchemaFile  = "evidence.schema.json"
)

type resolverDeps struct {
	dig.In
	DB        *gorm.DB
	Spaces    Spaces
	Published *publishedknowledge.Service `optional:"true"`
}

// Register provides the candidate and publish service to the application container.
// Without ENTERPRISE_SPACES the service is nil and the candidate routes answer 503;
// an invalid configuration fails startup instead of serving a partial scope.
func Register(container *dig.Container) error {
	if err := container.Provide(func(cfg *config.Config) (Spaces, error) {
		return LoadSpaces(cfg, os.Getenv(SpacesEnv))
	}); err != nil {
		return err
	}
	if err := container.Provide(func(spaces Spaces) source.CaptureScope { return spaces }); err != nil {
		return err
	}
	if err := container.Provide(func(deps resolverDeps) (*chatsource.Resolver, error) {
		if len(deps.Spaces.byKey) == 0 {
			return nil, nil
		}
		if deps.DB == nil {
			return nil, errors.New("enterprise chat sources need the database")
		}
		store := New(deps.DB, deps.Spaces)
		// Quick answers read published fields of the turn's pinned release (Q1b-2); without the
		// service they keep the Q1a behaviour.
		return chatsource.NewResolver(deps.Spaces, store, store, store).WithPublished(deps.Published), nil
	}); err != nil {
		return err
	}
	if err := container.Provide(func(
		cfg *config.Config, db *gorm.DB, knowledge interfaces.KnowledgeRepository,
		spaces Spaces, firstParse *appservice.G3FirstParseStore,
	) (*release.Service, error) {
		dir := strings.TrimSpace(os.Getenv(ContractsDirEnv))
		if dir == "" {
			dir = defaultContractsDir
		}
		var pages PageReader
		if captured := enterprisePages(spaces, knowledge, firstParse); captured != nil {
			pages = captured
		}
		return Production(db, knowledge, os.Getenv(SpacesEnv), dir, pages)
	}); err != nil {
		return err
	}
	if err := container.Provide(func(db *gorm.DB, spaces Spaces, releases *release.Service) *spotcheck.Service {
		if releases == nil {
			return nil
		}
		return spotcheck.NewService(New(db, spaces), releases)
	}); err != nil {
		return err
	}
	if err := container.Provide(func(db *gorm.DB, spaces Spaces, releases *release.Service) *expert.Service {
		if releases == nil {
			return nil
		}
		return expert.NewService(releases, New(db, spaces))
	}); err != nil {
		return err
	}
	// Confirmation items share the enterprise configuration: without Spaces the service is nil
	// and its routes answer 503 (S5b-3a).
	return container.Provide(func(db *gorm.DB, spaces Spaces, releases *release.Service) *confirm.Service {
		if releases == nil {
			return nil
		}
		return confirm.NewService(New(db, spaces))
	})
}

// enterprisePages reads captured artifacts of configured enterprise Spaces only, so evidence can
// only cite enterprise sources.
func enterprisePages(
	spaces Spaces, knowledge interfaces.KnowledgeRepository, firstParse *appservice.G3FirstParseStore,
) *source.Service {
	if firstParse == nil {
		return nil
	}
	return source.NewService(source.ArtifactStoreFunc(func(
		ctx context.Context, scope source.Scope, id string, attempt int64,
	) (*source.Artifact, error) {
		binding, err := spaces.Scope(scope.TenantID, scope.SpaceID)
		if err != nil {
			return nil, source.ErrNotFound
		}
		return firstParse.ReadSourceArtifact(ctx, knowledge, binding, id, attempt)
	}))
}

// LoadSpaces requires an active artifact signing key whenever capture is configured.
func LoadSpaces(cfg *config.Config, raw string) (Spaces, error) {
	spaces, err := ParseSpaces(raw)
	if err != nil || len(spaces.byKey) == 0 {
		return spaces, err
	}
	ring, err := config.DecodeSchemaWikiCitationTokenSigningRing(cfg)
	if err != nil {
		return Spaces{}, fmt.Errorf("enterprise capture signing ring: %w", err)
	}
	if ring.ActiveKeyID() == "" {
		return Spaces{}, errors.New("enterprise capture needs an active artifact signing key")
	}
	return spaces, nil
}

// Production builds the service for the configured Spaces. An empty configuration
// disables publishing (nil service); every other problem is an error.
func Production(
	db *gorm.DB, knowledge any, rawSpaces, contractsDir string, pages PageReader,
) (*release.Service, error) {
	spaces, err := ParseSpaces(rawSpaces)
	if err != nil {
		return nil, err
	}
	if len(spaces.byKey) == 0 {
		return nil, nil
	}
	revisions, ok := knowledge.(SourceRevisions)
	if db == nil || !ok || pages == nil {
		return nil, errors.New("enterprise publishing needs the database, knowledge revisions and captured pages")
	}
	schemas := map[string][]byte{}
	for name, file := range map[string]string{"candidate_bundle": bundleSchemaFile, "evidence": evidenceSchemaFile} {
		raw, err := os.ReadFile(filepath.Join(contractsDir, file))
		if err != nil {
			return nil, fmt.Errorf("enterprise publishing needs %s: %w", file, err)
		}
		schemas[name] = raw
	}
	if err := release.CheckSchemas(schemas); err != nil {
		return nil, fmt.Errorf("enterprise publishing: contract schemas do not compile: %w", err)
	}
	store := New(db, spaces)
	// Expert revision citations (S9a) resolve from the revision records; every other reference
	// keeps the captured-source path.
	resolver := expert.NewResolver(store, NewEvidence(spaces, revisions))
	verifier := expert.NewVerifier(store, NewEvidenceVerifier(spaces, pages))
	return release.NewService(store, resolver, schemas,
		release.WithPublisher(store), release.WithEvidenceVerifier(verifier),
		release.WithRetirer(store)), nil
}
