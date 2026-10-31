package service

import (
	"context"
	"errors"
	"os"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

// A scanned note is signed for a revision only when the bytes this parse actually read are that
// revision's file (#494 R1): the declared digests alone are not the binding.
func TestAScannedNoteIsBoundToTheBytesActuallyRead(t *testing.T) {
	for _, tc := range []struct {
		name   string
		read   []byte
		reason string
		page   int
	}{
		{"revision bytes", []byte("pdf"), source.NotCapturedScannedPage, 5},
		{"other bytes", []byte("other bytes"), source.NotCapturedNotRecorded, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			u := uploadToEnterpriseRawKB(t, &types.ReadResult{Error: "page 5 is scanned"})
			u.service.fileSvc = &revisionSourceFileServiceStub{data: tc.read}
			require.NoError(t, u.service.ProcessDocument(context.Background(), u.task))
			require.NotEqual(t, types.ParseStatusFailed, u.knowledge.ParseStatus)
			require.Empty(t, u.chunks.written, "the parse completes with zero chunks either way")

			_, err := u.pages(3)
			reason, page := notCapturedReason(t, err)
			require.Equal(t, tc.reason, reason)
			require.Equal(t, tc.page, page)
			if tc.reason == source.NotCapturedNotRecorded {
				_, err = os.ReadDir(u.store.root + "-notes")
				require.True(t, errors.Is(err, os.ErrNotExist), "no note is signed for bytes of another file")
			}
		})
	}
}
