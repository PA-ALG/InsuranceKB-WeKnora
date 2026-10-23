package releasestore

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
	"go.uber.org/dig"
	"gorm.io/gorm"

	appservice "github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

const oneSpace = `[{"tenant_id":7,"space_id":"space-1","raw_kb_id":"raw-1","wiki_kb_id":"wiki-1"}]`

func contractsDir(t *testing.T, schema string) string {
	t.Helper()
	dir := t.TempDir()
	require.NoError(t, os.WriteFile(filepath.Join(dir, bundleSchemaFile), []byte(schema), 0o600))
	evidence, err := os.ReadFile("../../../contracts/" + evidenceSchemaFile)
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(filepath.Join(dir, evidenceSchemaFile), evidence, 0o600))
	return dir
}

// stubPages stands in for the captured page reader; these tests never read a page.
type stubPages struct{}

func (stubPages) Pages(context.Context, source.Scope, string, int64) (*source.PageSet, error) {
	return nil, source.ErrNotFound
}

func TestProductionIsDisabledWithoutSpaces(t *testing.T) {
	service, err := Production(nil, nil, "  ", "/nonexistent", nil)
	require.NoError(t, err)
	require.Nil(t, service, "no Space configured means no enterprise publishing")
}

func TestProductionBuildsThePublishingServiceForConfiguredSpaces(t *testing.T) {
	service, err := Production(&gorm.DB{}, revisions{}, oneSpace, contractsDir(t, testSchema), stubPages{})
	require.NoError(t, err)
	require.NotNil(t, service)
}

func TestProductionRejectsEveryIncompleteConfiguration(t *testing.T) {
	good := contractsDir(t, testSchema)
	for name, probe := range map[string]struct {
		db        *gorm.DB
		knowledge any
		spaces    string
		dir       string
	}{
		"malformed spaces":         {&gorm.DB{}, revisions{}, `{`, good},
		"no database":              {nil, revisions{}, oneSpace, good},
		"no knowledge revisions":   {&gorm.DB{}, struct{}{}, oneSpace, good},
		"missing contract schema":  {&gorm.DB{}, revisions{}, oneSpace, t.TempDir()},
		"contract schema not JSON": {&gorm.DB{}, revisions{}, oneSpace, contractsDir(t, `{`)},
		"JSON but not a schema":    {&gorm.DB{}, revisions{}, oneSpace, contractsDir(t, `{"type":7}`)},
		"unsupplied reference": {
			&gorm.DB{}, revisions{}, oneSpace, contractsDir(t, `{"$ref":"bundle_member.schema.json"}`),
		},
	} {
		t.Run(name, func(t *testing.T) {
			service, err := Production(probe.db, probe.knowledge, probe.spaces, probe.dir, stubPages{})
			require.Error(t, err)
			require.Nil(t, service)
		})
	}
}

func TestRegisterProvidesANilServiceWhenPublishingIsNotConfigured(t *testing.T) {
	t.Setenv(SpacesEnv, "")
	container := dig.New()
	require.NoError(t, container.Provide(func() *config.Config { return &config.Config{} }))
	require.NoError(t, container.Provide(func() *gorm.DB { return &gorm.DB{} }))
	require.NoError(t, container.Provide(func() interfaces.KnowledgeRepository { return nil }))
	require.NoError(t, container.Provide(func() *appservice.G3FirstParseStore { return nil }))
	require.NoError(t, Register(container))
	require.NoError(t, container.Invoke(func(service *release.Service) {
		require.Nil(t, service)
	}))
}

// S4c-2b-2: configured Spaces need the captured page reader and the evidence contract,
// otherwise evidence could not be verified at submission.
func TestProductionRefusesSpacesWithoutEvidenceVerification(t *testing.T) {
	service, err := Production(&gorm.DB{}, revisions{}, oneSpace, contractsDir(t, testSchema), nil)
	require.Error(t, err)
	require.Nil(t, service)

	dir := contractsDir(t, testSchema)
	require.NoError(t, os.Remove(filepath.Join(dir, evidenceSchemaFile)))
	service, err = Production(&gorm.DB{}, revisions{}, oneSpace, dir, stubPages{})
	require.Error(t, err)
	require.Nil(t, service)
}
