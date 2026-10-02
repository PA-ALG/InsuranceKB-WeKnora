package im

import (
	"context"
	"fmt"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

type rejectedSearchService struct {
	interfaces.SessionService
	err error
}

func (s *rejectedSearchService) SearchKnowledge(
	context.Context, []string, []string, []types.TagScope, string,
) ([]*types.SearchResult, error) {
	return nil, s.err
}

func TestSearchCommandDisplaysCustodyDenial(t *testing.T) {
	for _, code := range []string{managed.ErrorCodeReleaseManaged, managed.ErrorCodeClassificationUnavailable} {
		cmd := newSearchCommand(&rejectedSearchService{
			err: fmt.Errorf("wrapped: %w", &managed.ReadError{Code: code}),
		}, nil)
		result, err := cmd.Execute(context.Background(), &CommandContext{}, []string{"query"})
		require.NoError(t, err)
		require.NotNil(t, result)
		require.Contains(t, result.Content, code)
	}
}
