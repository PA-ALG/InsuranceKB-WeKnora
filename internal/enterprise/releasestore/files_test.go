package releasestore

import (
	"bytes"
	"context"
	"errors"
	"io"
	"testing"

	"github.com/stretchr/testify/require"
	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

type lookupFunc func(ctx context.Context, tenantID uint64, id string) (*types.Knowledge, error)

func (f lookupFunc) GetKnowledgeByID(ctx context.Context, tenantID uint64, id string) (*types.Knowledge, error) {
	return f(ctx, tenantID, id)
}

type openerFunc func(ctx context.Context, id string) (io.ReadCloser, string, error)

func (f openerFunc) GetKnowledgeFile(ctx context.Context, id string) (io.ReadCloser, string, error) {
	return f(ctx, id)
}

func TestSourceFilesOpensOnlyKnowledgeOfTheSpaceRawKB(t *testing.T) {
	spaces, err := ParseSpaces(oneSpace)
	require.NoError(t, err)
	stored := map[string]*types.Knowledge{
		"k-1":     {ID: "k-1", TenantID: 7, KnowledgeBaseID: "raw-1"},
		"k-wiki":  {ID: "k-wiki", TenantID: 7, KnowledgeBaseID: "wiki-1"},
		"k-gone":  {ID: "k-gone", TenantID: 7, KnowledgeBaseID: "raw-1", DeletedAt: gorm.DeletedAt{Valid: true}},
		"k-other": {ID: "k-other", TenantID: 8, KnowledgeBaseID: "raw-1"},
	}
	lookup := lookupFunc(func(_ context.Context, _ uint64, id string) (*types.Knowledge, error) {
		if id == "k-down" {
			return nil, errors.New("database unavailable")
		}
		k, ok := stored[id]
		if !ok {
			return nil, repository.ErrKnowledgeNotFound
		}
		return k, nil
	})
	var opened []string
	opener := openerFunc(func(_ context.Context, id string) (io.ReadCloser, string, error) {
		opened = append(opened, id)
		return io.NopCloser(bytes.NewReader([]byte("%PDF"))), "terms.pdf", nil
	})
	open := SourceFiles(spaces, lookup, opener)
	scope := source.Scope{TenantID: 7, SpaceID: "space-1"}

	reader, name, err := open(context.Background(), scope, "k-1")
	require.NoError(t, err)
	require.Equal(t, "terms.pdf", name)
	require.NoError(t, reader.Close())

	for _, id := range []string{"k-wiki", "k-gone", "k-other", "k-missing"} {
		_, _, err := open(context.Background(), scope, id)
		require.ErrorIs(t, err, source.ErrNotFound, id)
	}
	_, _, err = open(context.Background(), source.Scope{TenantID: 7, SpaceID: "space-9"}, "k-1")
	require.ErrorIs(t, err, source.ErrNotFound, "an unconfigured Space opens nothing")
	_, _, err = open(context.Background(), scope, "k-down")
	require.Error(t, err)
	require.NotErrorIs(t, err, source.ErrNotFound, "an outage is not reported as a missing file")
	require.Equal(t, []string{"k-1"}, opened)

	_, _, err = SourceFiles(spaces, nil, opener)(context.Background(), scope, "k-1")
	require.ErrorIs(t, err, source.ErrNotFound)
}
