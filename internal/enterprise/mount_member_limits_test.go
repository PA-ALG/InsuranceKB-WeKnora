package enterprise_test

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

type largeReadPublisher struct {
	*publishStore
	rows []release.Member
}

func (p *largeReadPublisher) ReleaseSummary(context.Context, uint64, string) (release.Release, error) {
	return release.Release{ID: "rel", Epoch: 1}, nil
}

func (p *largeReadPublisher) MemberIndex(context.Context, uint64, string, string) (
	release.Release, []release.Member, error,
) {
	return release.Release{ID: "rel", Epoch: 1}, p.rows, nil
}

func (p *largeReadPublisher) LookupMembers(context.Context, uint64, string, string, []string) (
	release.Release, []release.Member, error,
) {
	return release.Release{ID: "rel", Epoch: 1}, p.rows, nil
}

func TestMountedFixedReadsRefuseOversizeBeforeSendingBodies(t *testing.T) {
	store := &largeReadPublisher{publishStore: newPublishStore()}
	service := release.NewService(store, nil, nil, release.WithPublisher(store))
	router := mountRouter(service, machineKey())
	for _, test := range []struct {
		method, path, body string
		rows               []release.Member
	}{
		{http.MethodGet, "member-index", "", make([]release.Member, 20001)},
		{http.MethodPost, "member-lookup", `{"slugs":["a"]}`, []release.Member{{
			LogicalSlug: "a", Kind: "claim", Payload: json.RawMessage(`"` + strings.Repeat("x", 8<<20) + `"`),
		}}},
	} {
		store.rows = test.rows
		out := request(router, test.method, spacePath+"/releases/rel/"+test.path, "test-key", []byte(test.body))
		require.Equal(t, http.StatusRequestEntityTooLarge, out.Code)
		require.Equal(t, "RELEASE_READ_LIMIT", code(t, out.Body.Bytes()))
		require.NotContains(t, out.Body.String(), "members")
	}
}
