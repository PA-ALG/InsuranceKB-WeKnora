package knowledge_test

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

type membersReader []release.Member

func (r membersReader) ReleaseByID(context.Context, uint64, string, string) (release.Release, error) {
	return release.Release{ID: pinned, Epoch: 1, Members: r}, nil
}

func searchPages(t *testing.T, members ...release.Member) ([]knowledge.Page, int, error) {
	t.Helper()
	service := knowledge.NewService(membersReader(members))
	return service.SearchPages(context.Background(), tenant, space, pinned, "等待期", "", 0)
}

// R1 (#260): page_key is opaque in the S6c contract; only the member identity must agree.
func TestPageKeyNeedNotRepeatThePageType(t *testing.T) {
	pages, total, err := searchPages(t, member("wiki_page", "wiki/1828/waiting-period", map[string]any{
		"page_key": "waiting-period", "entity_refs": []string{"1828"}, "title": "等待期", "page_type": "concept",
		"content": "正文。", "origin": "MODEL_GENERATED",
	}))
	require.NoError(t, err)
	require.Equal(t, 1, total)
	require.Equal(t, "wiki/1828/waiting-period", pages[0].Slug)
}

// R2 (#260): one bad evidence page is skipped, keeping the other entries and their indexes.
func TestInvalidEvidencePagesAreSkippedWithoutFailingTheRead(t *testing.T) {
	raw := []json.RawMessage{
		json.RawMessage(`{"quote":"小数页码","locator":{"page":1.5}}`),
		json.RawMessage(`{"quote":"字符串页码","locator":{"page":"3"}}`),
		json.RawMessage(`{"quote":"超大页码","locator":{"page":99999999999999999999}}`),
		json.RawMessage(`{"quote":"负数页码","locator":{"page":-2}}`),
		json.RawMessage(`{"quote":["不是文本"],"locator":{"page":2}}`),
		json.RawMessage(`{"quote":"合法出处","locator":{"page":3},"source_ref":"source:v1:k1:1:abc"}`),
	}
	pages, _, err := searchPages(t, member("wiki_page", "wiki/1828/concept/deng-dai-qi", map[string]any{
		"page_key": "concept/deng-dai-qi", "entity_refs": []string{"1828"}, "title": "等待期", "page_type": "concept",
		"content": "正文。", "origin": "MODEL_GENERATED", "evidence": raw,
	}))
	require.NoError(t, err)
	require.Equal(t, []knowledge.Evidence{{Index: 5, Quote: "合法出处", Page: 3, SourceRef: "source:v1:k1:1:abc"}},
		pages[0].Evidence)
}

// R3 (#260): a page payload that is not a valid object is a typed INVALID_REQUEST.
func TestMalformedPagePayloadIsATypedInvalidRequest(t *testing.T) {
	for _, payload := range []string{`{"page_key":`, `{"page_key":"x","title":3}`} {
		bad := release.Member{
			Kind: "wiki_page", LogicalSlug: "wiki/1828/x", Payload: json.RawMessage(payload),
			MemberDigest: "d", AccessScope: "space",
		}
		_, _, err := searchPages(t, bad)
		var typed *release.Error
		require.True(t, errors.As(err, &typed), "payload %s gave %v", payload, err)
		require.Equal(t, release.ErrorInvalidRequest, typed.Code)
	}
}
