package container

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
	"go.uber.org/dig"
	"gorm.io/gorm"
)

type (
	managedWikiFixture struct{ interfaces.WikiPageService }
	managedKBFixture   struct {
		interfaces.KnowledgeBaseService
	}
)

func (*managedKBFixture) GetKnowledgeBaseByIDOnly(context.Context, string) (*types.KnowledgeBase, error) {
	return &types.KnowledgeBase{ID: "wiki", TenantID: 42}, nil
}

func TestManagedWriteAssemblyHasNonNilClassifierAndToolGuard(t *testing.T) {
	c := dig.New()
	require.NoError(t, c.Provide(func() *gorm.DB { return nil }))
	require.NoError(t, c.Provide(func() interfaces.WikiPageService { return &managedWikiFixture{} }))
	require.NoError(t, c.Provide(func() interfaces.KnowledgeBaseService { return &managedKBFixture{} }))
	require.NoError(t, managed.Register(c))
	require.NoError(t, c.Invoke(func(classifier managed.Classifier, wiki interfaces.WikiPageService) {
		require.NotNil(t, classifier)
		guard, ok := wiki.(interface {
			CheckWikiWrite(context.Context, string) error
		})
		require.True(t, ok)
		require.NotNil(t, guard)
		ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(42))
		require.ErrorContains(t, guard.CheckWikiWrite(ctx, "wiki"),
			managed.ErrorCodeClassificationUnavailable, "missing DB must fail closed")
	}))
}

func TestProductionManagedWriteDependenciesResolve(t *testing.T) {
	t.Setenv("REDIS_ADDR", "")
	c := BuildContainer(dig.New(dig.DryRun(true)))
	require.NoError(t, c.Invoke(func(managed.Classifier, interfaces.WikiPageService) {}))
}
