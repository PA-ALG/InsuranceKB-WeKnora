package releasestore

import (
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

func TestSourceRefsUsesPlatformParserAndPreservesPrefixBoundary(t *testing.T) {
	for name, raw := range map[string]string{
		"invalid fingerprint": "source:v1:k-1:1:abc",
		"missing fields":      "source:v1:k-1",
		"overflowing attempt": "source:v1:k-1:9223372036854775808:" + strings.Repeat("a", 64),
	} {
		t.Run(name, func(t *testing.T) {
			_, err := sourceRefs([]release.Member{{EvidenceRefs: []string{raw}}})
			require.ErrorIs(t, err, repository.ErrRevisionSourceUnavailable)
		})
	}
	refs, err := sourceRefs([]release.Member{{EvidenceRefs: []string{
		"external:document", "source:v2:k-1:1:abc", postgresSourceRef, postgresSourceRef,
	}}})
	require.NoError(t, err)
	require.Equal(t, []repository.RevisionRef{{KnowledgeID: "k-1", ParseAttempt: 1}}, refs)
}
