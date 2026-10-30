package managed

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

type acrossWiki struct {
	interfaces.WikiPageService
	calls int
}

func (w *acrossWiki) SearchPagesAcross(context.Context, []string, string, int) ([]*types.WikiPage, error) {
	w.calls++
	return []*types.WikiPage{{Slug: "p"}}, nil
}

type acrossClassifier map[string]Role

func (c acrossClassifier) Classify(_ context.Context, _ uint64, kbID string) (Role, error) {
	role, ok := c[kbID]
	if !ok {
		return Role{}, errors.New("unknown")
	}
	return role, nil
}

type acrossLookup struct{}

func (acrossLookup) GetKnowledgeBaseByIDOnly(_ context.Context, id string) (*types.KnowledgeBase, error) {
	return &types.KnowledgeBase{ID: id, TenantID: 7}, nil
}

func TestCrossKBWikiSearchRefusesReleaseManagedKnowledgeBases(t *testing.T) {
	classifier := acrossClassifier{
		"plain":   {Kind: KindNone, State: StateUnmanaged},
		"managed": {Kind: KindWiki, State: StateActive},
	}
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))

	inner := &acrossWiki{}
	svc := WrapWikiService(inner, classifier, acrossLookup{})
	pages, err := svc.SearchPagesAcross(ctx, []string{"plain"}, "q", 5)
	require.NoError(t, err)
	require.Len(t, pages, 1)

	_, err = svc.SearchPagesAcross(ctx, []string{"plain", "managed"}, "q", 5)
	var readErr *ReadError
	require.ErrorAs(t, err, &readErr)
	require.Equal(t, ErrorCodeReleaseManaged, readErr.Code)
	require.Equal(t, 1, inner.calls, "a managed KB in the list must stop the native search")

	_, err = svc.SearchPagesAcross(context.Background(), []string{"plain"}, "q", 5)
	require.Error(t, err, "no tenant context fails closed")
}
