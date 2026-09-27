package service

import (
	"context"
	"fmt"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestG3SourceCacheEvictsOneColdEntryInsteadOfAll(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	s, _, scope, evidence, block := nativeIndexFixture830G2(t)
	readySourceReuseResource830G3(s)
	s.sourceReuse = newConceptSourceReuseStore830G3(sourceReuseTestCodec830G3(t))
	_, _, err := s.verifyEvidence(context.Background(), scope, evidence, &block)
	require.NoError(t, err)
	key, err := conceptSourceReuseKey830G3(evidence.ConceptSourceIdentity830G2, s.revisions.(*conceptKnowledgeStub830G2).source.BindingDigest)
	require.NoError(t, err)
	seed := s.sourceReuse.entries[key].record
	source := s.revisions.(*conceptKnowledgeStub830G2).source
	load := func(key string) {
		_, err := s.sourceReuse.load(context.Background(), key, evidence.ConceptSourceIdentity830G2, source, func() (*conceptSourceReuseRecord830G3, error) { return &seed, nil })
		require.NoError(t, err)
	}
	for i := 0; i < 15; i++ {
		load(fmt.Sprintf("document-%d", i))
	}
	load(key) // This recently used document must survive the next insertion.
	load("document-16")
	require.Len(t, s.sourceReuse.entries, 16, "capacity overflow must evict only one entry")
	require.Contains(t, s.sourceReuse.entries, key, "the active source index should remain resident")
	require.NotContains(t, s.sourceReuse.entries, "document-0", "evict the least recently used source")
}
