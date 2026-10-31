package file

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"
)

// The revision-pin check before a physical delete is ours. The test wraps the upstream stubs
// (resource_catalog_test.go, kept byte-identical) to fail MarkDeleted and count physical deletes.
type pinRejectingCatalog struct {
	*catalogStub
	markDeleteErr error
	markCalls     int
}

func (c *pinRejectingCatalog) MarkDeleted(context.Context, string) error {
	c.markCalls++
	return c.markDeleteErr
}

type countingPhysicalFiles struct {
	*physicalFileStub
	deletes int
}

func (s *countingPhysicalFiles) DeleteFile(context.Context, string) error {
	s.deletes++
	return nil
}

func TestResourceCatalogFileServiceChecksPinnedGuardBeforePhysicalDelete(t *testing.T) {
	inner := &countingPhysicalFiles{physicalFileStub: &physicalFileStub{savedPath: "local://7/immutable/a.pdf"}}
	catalog := &pinRejectingCatalog{
		catalogStub: &catalogStub{}, markDeleteErr: errors.New("resource is revision-pinned"),
	}
	svc := NewResourceCatalogFileService(inner, catalog)
	ref, err := svc.SaveBytes(context.Background(), []byte("pdf"), 7, "a.pdf", false)
	require.NoError(t, err)

	err = svc.DeleteFile(context.Background(), ref)
	require.ErrorContains(t, err, "revision-pinned")
	require.Equal(t, 1, catalog.markCalls)
	require.Zero(t, inner.deletes)
}
