package releasestore

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"go.uber.org/dig"
	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
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
)

// Register provides the candidate and publish service to the application container.
// Without ENTERPRISE_SPACES the service is nil and the candidate routes answer 503;
// an invalid configuration fails startup instead of serving a partial scope.
func Register(container *dig.Container) error {
	return container.Provide(func(
		cfg *config.Config, db *gorm.DB, knowledge interfaces.KnowledgeRepository,
	) (*release.Service, error) {
		dir := strings.TrimSpace(os.Getenv(ContractsDirEnv))
		if dir == "" {
			dir = defaultContractsDir
		}
		return Production(db, knowledge, os.Getenv(SpacesEnv), dir, reservedScopes(cfg)...)
	})
}

// Production builds the service for the configured Spaces. An empty configuration
// disables publishing (nil service); every other problem is an error.
func Production(
	db *gorm.DB, knowledge any, rawSpaces, contractsDir string, reserved ...types.WikiReleaseScope,
) (*release.Service, error) {
	spaces, err := ParseSpaces(rawSpaces, reserved...)
	if err != nil {
		return nil, err
	}
	if len(spaces.byKey) == 0 {
		return nil, nil
	}
	revisions, ok := knowledge.(SourceRevisions)
	if db == nil || !ok {
		return nil, errors.New("enterprise publishing needs the database and knowledge revisions")
	}
	schema, err := os.ReadFile(filepath.Join(contractsDir, bundleSchemaFile))
	if err != nil {
		return nil, fmt.Errorf("enterprise publishing needs %s: %w", bundleSchemaFile, err)
	}
	if !json.Valid(schema) {
		return nil, fmt.Errorf("enterprise publishing: %s is not valid JSON", bundleSchemaFile)
	}
	store := New(db, spaces)
	return release.NewService(
		store, NewEvidence(spaces, revisions), map[string][]byte{"candidate_bundle": schema},
		release.WithPublisher(store),
	), nil
}

// reservedScopes are the scopes enterprise Spaces may not reuse: the G3 path keeps
// its own Head. The configured fields are reserved even while the G3 policy is
// outside its validity window, so a Space can never take over a G3 wiki KB.
func reservedScopes(cfg *config.Config) []types.WikiReleaseScope {
	if cfg == nil || cfg.G3PlatformProcessing == nil {
		return nil
	}
	g3 := cfg.G3PlatformProcessing
	return []types.WikiReleaseScope{{
		TenantID: g3.TenantID, SpaceID: g3.SpaceID, RawKBID: g3.RawKBID, WikiKBID: g3.WikiKBID,
	}}
}
