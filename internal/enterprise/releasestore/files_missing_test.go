package releasestore

// S5b-3d-2 acceptance (protected, written by Claude, issue #373 R3): a knowledge whose stored
// file is physically gone is a missing source (typed SOURCE_NOT_FOUND, 404), not an
// unavailable service. Every file backend that reports absence through fs.ErrNotExist is
// covered; other storage failures stay unavailable.

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestSourceFilesTreatsAPhysicallyMissingFileAsANotFoundSource(t *testing.T) {
	spaces, err := ParseSpaces(oneSpace)
	require.NoError(t, err)
	lookup := lookupFunc(func(_ context.Context, _ uint64, id string) (*types.Knowledge, error) {
		return &types.Knowledge{ID: id, TenantID: 7, KnowledgeBaseID: "raw-1"}, nil
	})
	scope := source.Scope{TenantID: 7, SpaceID: "space-1"}
	for name, failure := range map[string]error{
		"os open":      fmt.Errorf("failed to open file: %w", os.ErrNotExist),
		"fs not exist": fmt.Errorf("read object: %w", fs.ErrNotExist),
		"path error":   &fs.PathError{Op: "open", Path: "/data/k-1.pdf", Err: os.ErrNotExist},
	} {
		t.Run(name, func(t *testing.T) {
			files := openerFunc(func(context.Context, string) (io.ReadCloser, string, error) {
				return nil, "", failure
			})
			_, _, err := SourceFiles(spaces, lookup, files)(context.Background(), scope, "k-1")
			require.ErrorIs(t, err, source.ErrNotFound)
		})
	}

	down := errors.New("object store down")
	files := openerFunc(func(context.Context, string) (io.ReadCloser, string, error) { return nil, "", down })
	_, _, err = SourceFiles(spaces, lookup, files)(context.Background(), scope, "k-1")
	require.ErrorIs(t, err, down, "other storage failures keep their cause")
	require.NotErrorIs(t, err, source.ErrNotFound)
}
