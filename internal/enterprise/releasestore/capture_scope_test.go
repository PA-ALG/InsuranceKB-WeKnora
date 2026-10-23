// S4c-2c acceptance: configured enterprise Spaces define which RAW knowledge bases
// must capture their first parse, and a deployment with Spaces refuses to start
// without the key ring that seals those artifacts (Spec §3.1, §3.5).
// Protected file: written by Claude.
//
// RED until source.CaptureScope, Spaces.RawKB, LoadSpaces and the Register
// providers exist. No database, file system or network is used.
package releasestore

import (
	"crypto/ed25519"
	"encoding/base64"
	"testing"

	"github.com/stretchr/testify/require"
	"go.uber.org/dig"
	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

var _ source.CaptureScope = Spaces{}

const twoTenantSpaces = `[
	{"tenant_id":7,"space_id":"space-1","raw_kb_id":"raw-1","wiki_kb_id":"wiki-1"},
	{"tenant_id":8,"space_id":"space-2","raw_kb_id":"raw-2","wiki_kb_id":"wiki-2"}
]`

// artifactSigning returns a complete citation-token ring. Test-only key material
// is generated in memory; no deployment setting is read.
func artifactSigning(t *testing.T) *config.SchemaWikiSigningConfig {
	t.Helper()
	_, private, err := ed25519.GenerateKey(nil)
	require.NoError(t, err)
	return &config.SchemaWikiSigningConfig{
		CitationTokenSigningKeys: []config.SchemaWikiEd25519PrivateKeyConfig{{
			KeyID: "artifact-seal", PrivateKeyBase64: base64.RawURLEncoding.EncodeToString(private),
		}},
		ActiveCitationTokenKeyID: "artifact-seal",
	}
}

func TestSpacesReportOnlyTheirOwnRawKBsAsCaptureScope(t *testing.T) {
	spaces, err := LoadSpaces(&config.Config{SchemaWikiSigning: artifactSigning(t)}, twoTenantSpaces)
	require.NoError(t, err)
	require.True(t, spaces.RawKB(7, "raw-1"))
	require.True(t, spaces.RawKB(8, "raw-2"))
	for _, probe := range []struct {
		tenant uint64
		kb     string
	}{
		{8, "raw-1"}, {7, "raw-2"}, // a RAW KB belongs to exactly one tenant
		{7, "wiki-1"}, {7, "space-1"}, {7, ""}, {0, "raw-1"},
	} {
		require.False(t, spaces.RawKB(probe.tenant, probe.kb), "tenant %d kb %q", probe.tenant, probe.kb)
	}
	scope, err := spaces.Scope(7, "space-1")
	require.NoError(t, err)
	require.Equal(t, "raw-1", scope.RawKBID, "LoadSpaces keeps the S4c-2a Space resolution")
	require.False(t, Spaces{}.RawKB(7, "raw-1"), "a deployment without Spaces captures no enterprise KB")
}

func TestLoadSpacesRequiresTheArtifactSigningRingOnlyWhenSpacesAreConfigured(t *testing.T) {
	for name, cfg := range map[string]*config.Config{
		"no config":           nil,
		"no signing config":   {},
		"no citation ring":    {SchemaWikiSigning: &config.SchemaWikiSigningConfig{}},
		"ring without a key":  {SchemaWikiSigning: &config.SchemaWikiSigningConfig{ActiveCitationTokenKeyID: "seal"}},
		"active key not kept": {SchemaWikiSigning: withActiveKey(artifactSigning(t), "missing")},
	} {
		t.Run(name, func(t *testing.T) {
			_, err := LoadSpaces(cfg, oneSpace)
			require.Error(t, err, "captured artifacts could not be sealed, so the process must not start")
		})
	}
	for name, cfg := range map[string]*config.Config{
		"no config":         nil,
		"no signing config": {},
	} {
		t.Run("unconfigured Spaces with "+name, func(t *testing.T) {
			spaces, err := LoadSpaces(cfg, "  ")
			require.NoError(t, err, "without ENTERPRISE_SPACES nothing needs sealing")
			require.False(t, spaces.RawKB(7, "raw-1"))
		})
	}
}

func withActiveKey(signing *config.SchemaWikiSigningConfig, keyID string) *config.SchemaWikiSigningConfig {
	signing.ActiveCitationTokenKeyID = keyID
	return signing
}

func registeredContainer(t *testing.T, cfg *config.Config, spaces string) *dig.Container {
	t.Helper()
	t.Setenv(SpacesEnv, spaces)
	container := dig.New()
	require.NoError(t, container.Provide(func() *config.Config { return cfg }))
	require.NoError(t, container.Provide(func() *gorm.DB { return &gorm.DB{} }))
	require.NoError(t, container.Provide(func() interfaces.KnowledgeRepository { return nil }))
	require.NoError(t, Register(container))
	return container
}

func TestRegisterFailsStartupWhenConfiguredSpacesCannotSealArtifacts(t *testing.T) {
	container := registeredContainer(t, &config.Config{}, oneSpace)
	require.Error(t, container.Invoke(func(Spaces) {}))
	require.Error(t, container.Invoke(func(source.CaptureScope) {}))
}

func TestRegisterProvidesTheSpacesAndTheirCaptureScope(t *testing.T) {
	configured := registeredContainer(t, &config.Config{SchemaWikiSigning: artifactSigning(t)}, oneSpace)
	require.NoError(t, configured.Invoke(func(scope source.CaptureScope, spaces Spaces) {
		require.True(t, scope.RawKB(7, "raw-1"))
		require.False(t, scope.RawKB(7, "wiki-1"))
		resolved, err := spaces.Scope(7, "space-1")
		require.NoError(t, err)
		require.Equal(t, "raw-1", resolved.RawKBID)
	}))
	unconfigured := registeredContainer(t, &config.Config{}, "")
	require.NoError(t, unconfigured.Invoke(func(scope source.CaptureScope, spaces Spaces) {
		require.False(t, scope.RawKB(7, "raw-1"))
		_, err := spaces.Scope(7, "space-1")
		require.Error(t, err)
	}), "without ENTERPRISE_SPACES the process starts and only the G3 scope is captured")
}
