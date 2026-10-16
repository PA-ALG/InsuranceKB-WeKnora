package source_test

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/source"
)

func TestPagesRejectMalformedArtifactMetadataAndJSON(t *testing.T) {
	for name, mutate := range map[string]func(*source.Artifact){
		"wrong knowledge":     func(a *source.Artifact) { a.KnowledgeID = "other" },
		"wrong attempt":       func(a *source.Artifact) { a.ParseAttempt++ },
		"invalid file hash":   func(a *source.Artifact) { a.FileSHA256 = "invalid" },
		"invalid parser hash": func(a *source.Artifact) { a.ParserIdentitySHA256 = "invalid" },
		"internal filename":   func(a *source.Artifact) { a.FileName = "/storage/document.pdf" },
		"malformed JSON":      func(a *source.Artifact) { a.NativeJSON = []byte(`{`) },
		"null JSON":           func(a *source.Artifact) { a.NativeJSON = []byte(`null`) },
		"missing range": func(a *source.Artifact) {
			a.NativeJSON = []byte(`{"pages":[{"page_number":1,"page_text_sha256":"` + sha("") + `"}]}`)
		},
		"invalid UTF8": func(a *source.Artifact) { a.Markdown = string([]byte{0xff}) },
	} {
		t.Run(name, func(t *testing.T) {
			a := artifact(t, "text")
			mutate(a)
			_, err := source.NewService(&store{artifact: a}).Pages(context.Background(), scope, "k-1", 2)
			require.Equal(t, "PARSE_ARTIFACT_INTEGRITY", code(t, err))
		})
	}
}

func TestPagesAllowEmptyPagesWithoutChangingTheirText(t *testing.T) {
	a := artifact(t, "", "\r\n𠮷 \t", "")
	set, err := source.NewService(&store{artifact: a}).Pages(context.Background(), scope, "k-1", 2)
	require.NoError(t, err)
	require.Equal(t, "", set.Pages[0].Text)
	require.Equal(t, "\r\n𠮷 \t", set.Pages[1].Text)
	require.Equal(t, "", set.Pages[2].Text)
}

func TestPagesFailClosedForNilStoreAndMissingArtifact(t *testing.T) {
	for _, s := range []source.ArtifactStore{nil, &store{}} {
		_, err := source.NewService(s).Pages(context.Background(), scope, "k-1", 2)
		require.Equal(t, "SOURCE_UNAVAILABLE", code(t, err))
	}
	_, err := source.NewService(&store{err: errors.Join(errors.New("backend"), source.ErrNotFound)}).
		Pages(context.Background(), scope, "k-1", 2)
	require.Equal(t, "SOURCE_NOT_FOUND", code(t, err))
}

func TestPagesRequireScopeAndHonorCancellationBeforeLoading(t *testing.T) {
	s := &store{}
	for _, invalid := range []source.Scope{{SpaceID: "space-1"}, {TenantID: 7}} {
		_, err := source.NewService(s).Pages(context.Background(), invalid, "k-1", 2)
		require.Equal(t, "INVALID_REQUEST", code(t, err))
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := source.NewService(s).Pages(ctx, scope, "k-1", 2)
	require.Equal(t, "SOURCE_UNAVAILABLE", code(t, err))
	require.Zero(t, s.calls)
}

func TestPagesSanitizeInvalidAuthorizationFromThePlatformAdapter(t *testing.T) {
	_, err := source.NewService(&store{err: &source.Error{
		Code: source.ErrorInvalidRequest, Detail: "private policy diagnostic",
	}}).Pages(context.Background(), scope, "k-1", 2)
	require.Equal(t, "INVALID_REQUEST", code(t, err))
	require.NotContains(t, err.Error(), "private policy diagnostic")
}
