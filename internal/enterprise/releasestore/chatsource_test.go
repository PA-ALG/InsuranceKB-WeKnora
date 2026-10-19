package releasestore

import (
	"testing"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/stretchr/testify/require"
	"go.uber.org/dig"
	"gorm.io/gorm"
)

func TestChatSourceSpacesRejectEveryKBRoleAmbiguity(t *testing.T) {
	for _, second := range []string{
		`{"tenant_id":7,"space_id":"s2","raw_kb_id":"raw","wiki_kb_id":"wiki2"}`,
		`{"tenant_id":7,"space_id":"s2","raw_kb_id":"wiki","wiki_kb_id":"wiki2"}`,
		`{"tenant_id":7,"space_id":"s2","raw_kb_id":"raw2","wiki_kb_id":"raw"}`,
		`{"tenant_id":8,"space_id":"s2","raw_kb_id":"raw","wiki_kb_id":"wiki2"}`,
	} {
		_, err := ParseSpaces(`[{"tenant_id":7,"space_id":"s1","raw_kb_id":"raw","wiki_kb_id":"wiki"},` + second + `]`)
		require.Error(t, err)
	}
	spaces, err := ParseSpaces(oneSpace)
	require.NoError(t, err)
	space, role, ok := spaces.SpaceOf(7, "raw-1")
	require.Equal(t, "space-1", space)
	require.Equal(t, chatsource.Role("raw"), role)
	require.True(t, ok)
	_, role, ok = spaces.SpaceOf(7, "wiki-1")
	require.True(t, ok)
	require.Equal(t, chatsource.Role("wiki"), role)
	_, _, ok = spaces.SpaceOf(8, "raw-1")
	require.False(t, ok)
}

func TestChatSourceSpaceOwnerReadsTheCompleteRegistry(t *testing.T) {
	spaces, err := ParseSpaces(oneSpace)
	require.NoError(t, err)
	owner, space, role, ok := spaces.SpaceOwner("raw-1")
	require.True(t, ok)
	require.Equal(t, uint64(7), owner)
	require.Equal(t, "space-1", space)
	require.Equal(t, chatsource.RoleRaw, role)
	_, _, _, ok = spaces.SpaceOwner("ordinary")
	require.False(t, ok)
}

func TestChatSourceRegisterDisablesResolverWithoutSpaces(t *testing.T) {
	t.Setenv(SpacesEnv, "")
	container := dig.New()
	require.NoError(t, container.Provide(func() *config.Config { return &config.Config{} }))
	require.NoError(t, container.Provide(func() *gorm.DB { return &gorm.DB{} }))
	require.NoError(t, Register(container))
	require.NoError(t, container.Invoke(func(resolver *chatsource.Resolver) {
		require.Nil(t, resolver, "empty enterprise configuration keeps the original chat paths")
	}))
}

func TestChatSourceRegisterKeepsResolverForConfiguredSpaces(t *testing.T) {
	t.Setenv(SpacesEnv, oneSpace)
	container := dig.New()
	require.NoError(t, container.Provide(func() *config.Config {
		return &config.Config{SchemaWikiSigning: artifactSigning(t)}
	}))
	require.NoError(t, container.Provide(func() *gorm.DB { return &gorm.DB{} }))
	require.NoError(t, Register(container))
	require.NoError(t, container.Invoke(func(resolver *chatsource.Resolver) {
		require.NotNil(t, resolver)
		space, role, ok := resolver.SpaceOf(7, "raw-1")
		require.True(t, ok)
		require.Equal(t, "space-1", space)
		require.Equal(t, chatsource.RoleRaw, role)
	}))
}
