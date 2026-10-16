package releasestore

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
	"go.uber.org/dig"
	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

const oneSpace = `[{"tenant_id":7,"space_id":"space-1","raw_kb_id":"raw-1","wiki_kb_id":"wiki-1"}]`

func contractsDir(t *testing.T, schema string) string {
	t.Helper()
	dir := t.TempDir()
	require.NoError(t, os.WriteFile(filepath.Join(dir, bundleSchemaFile), []byte(schema), 0o600))
	return dir
}

func TestProductionIsDisabledWithoutSpaces(t *testing.T) {
	service, err := Production(nil, nil, "  ", "/nonexistent")
	require.NoError(t, err)
	require.Nil(t, service, "no Space configured means no enterprise publishing")
}

func TestProductionBuildsThePublishingServiceForConfiguredSpaces(t *testing.T) {
	service, err := Production(&gorm.DB{}, revisions{}, oneSpace, contractsDir(t, testSchema))
	require.NoError(t, err)
	require.NotNil(t, service)
}

func TestProductionRejectsEveryIncompleteConfiguration(t *testing.T) {
	g3 := types.WikiReleaseScope{TenantID: 7, SpaceID: "space-1", RawKBID: "g3raw", WikiKBID: "g3wiki"}
	good := contractsDir(t, testSchema)
	for name, probe := range map[string]struct {
		db        *gorm.DB
		knowledge any
		spaces    string
		dir       string
		reserved  []types.WikiReleaseScope
	}{
		"malformed spaces":         {&gorm.DB{}, revisions{}, `{`, good, nil},
		"reuses the G3 Space":      {&gorm.DB{}, revisions{}, oneSpace, good, []types.WikiReleaseScope{g3}},
		"no database":              {nil, revisions{}, oneSpace, good, nil},
		"no knowledge revisions":   {&gorm.DB{}, struct{}{}, oneSpace, good, nil},
		"missing contract schema":  {&gorm.DB{}, revisions{}, oneSpace, t.TempDir(), nil},
		"contract schema not JSON": {&gorm.DB{}, revisions{}, oneSpace, contractsDir(t, `{`), nil},
		"JSON but not a schema":    {&gorm.DB{}, revisions{}, oneSpace, contractsDir(t, `{"type":7}`), nil},
		"unsupplied reference": {
			&gorm.DB{}, revisions{}, oneSpace, contractsDir(t, `{"$ref":"bundle_member.schema.json"}`), nil,
		},
	} {
		t.Run(name, func(t *testing.T) {
			service, err := Production(probe.db, probe.knowledge, probe.spaces, probe.dir, probe.reserved...)
			require.Error(t, err)
			require.Nil(t, service)
		})
	}
}

func TestReservedScopesAlwaysIncludeTheConfiguredG3Scope(t *testing.T) {
	require.Empty(t, reservedScopes(nil))
	cfg := &config.Config{G3PlatformProcessing: &config.G3PlatformProcessingConfig{
		Enabled: false, TenantID: 7, SpaceID: "g3", RawKBID: "r", WikiKBID: "w",
	}}
	require.Equal(t, []types.WikiReleaseScope{{TenantID: 7, SpaceID: "g3", RawKBID: "r", WikiKBID: "w"}},
		reservedScopes(cfg), "a disabled or expired G3 policy still reserves its Space and wiki KB")
}

func TestRegisterProvidesANilServiceWhenPublishingIsNotConfigured(t *testing.T) {
	t.Setenv(SpacesEnv, "")
	container := dig.New()
	require.NoError(t, container.Provide(func() *config.Config { return &config.Config{} }))
	require.NoError(t, container.Provide(func() *gorm.DB { return &gorm.DB{} }))
	require.NoError(t, container.Provide(func() interfaces.KnowledgeRepository { return nil }))
	require.NoError(t, Register(container))
	require.NoError(t, container.Invoke(func(service *release.Service) {
		require.Nil(t, service)
	}))
}
