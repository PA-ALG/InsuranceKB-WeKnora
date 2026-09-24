package types

import (
	"context"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

type cancelAtBoundaryContext struct {
	context.Context
	checks, cancelAt int
}

func (c *cancelAtBoundaryContext) Err() error {
	c.checks++
	if c.checks >= c.cancelAt {
		return context.Canceled
	}
	return nil
}

func TestBatchConceptOperationCanceledAtBoundaries(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	for _, boundary := range []int{1, 2, 3, 4, 5} {
		ctx := &cancelAtBoundaryContext{Context: context.Background(), cancelAt: boundary}
		_, canonical, members, err := ValidateBatchConceptOperation830G3(ctx, raw)
		require.ErrorIs(t, err, context.Canceled, "boundary %d", boundary)
		require.Nil(t, canonical)
		require.Nil(t, members)
	}
}

func TestBatchConceptOperationPreservesCanonicalAndMembers(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	old, canonical, err := CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	members, err := old.SnapshotMembers()
	require.NoError(t, err)
	got, gotCanonical, gotMembers, err := ValidateBatchConceptOperation830G3(context.Background(), raw)
	require.NoError(t, err)
	require.Equal(t, old, got)
	require.Equal(t, canonical, gotCanonical)
	require.Equal(t, members, gotMembers)
}
