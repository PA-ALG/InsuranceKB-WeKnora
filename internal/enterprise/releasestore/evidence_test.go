package releasestore

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

var fileSHA = strings.Repeat("ab", 32)

type revisions struct {
	knowledge map[string]*types.Knowledge
	revisions map[string]*types.KnowledgeRevision
	err       error
}

func (r revisions) GetKnowledgeByID(_ context.Context, tenantID uint64, id string) (*types.Knowledge, error) {
	if r.err != nil {
		return nil, r.err
	}
	k, ok := r.knowledge[id]
	if !ok || k.TenantID != tenantID {
		return nil, repository.ErrKnowledgeNotFound
	}
	return k, nil
}

func (r revisions) GetRevision(_ context.Context, knowledgeID string, attempt int64) (*types.KnowledgeRevision, error) {
	rev, ok := r.revisions[knowledgeID]
	if !ok || rev.ParseAttempt != attempt {
		return nil, repository.ErrKnowledgeNotFound
	}
	return rev, nil
}

func resolver(t *testing.T, err error) *Evidence {
	t.Helper()
	spaces, parseErr := ParseSpaces(`[{"tenant_id":7,"space_id":"space-1","raw_kb_id":"raw-1","wiki_kb_id":"wiki-1"}]`)
	require.NoError(t, parseErr)
	return NewEvidence(spaces, revisions{
		knowledge: map[string]*types.Knowledge{
			"k-1":     {ID: "k-1", TenantID: 7, KnowledgeBaseID: "raw-1"},
			"k-other": {ID: "k-other", TenantID: 7, KnowledgeBaseID: "raw-elsewhere"},
		},
		revisions: map[string]*types.KnowledgeRevision{
			"k-1":     {KnowledgeID: "k-1", ParseAttempt: 2, FileSHA256: fileSHA},
			"k-other": {KnowledgeID: "k-other", ParseAttempt: 1, FileSHA256: fileSHA},
		},
		err: err,
	})
}

// memoryStore is the smallest release.Store: the resolver is exercised through
// Service.Receive, which is what attaches the authenticated scope to the context.
type memoryStore struct{}

func (memoryStore) CreateCandidate(
	_ context.Context, c release.Candidate, _ release.Bundle,
) (release.Candidate, error) {
	c.ID, c.Status = "candidate-1", "created"
	return c, nil
}

func (memoryStore) CandidateByID(context.Context, uint64, string, string) (release.Candidate, error) {
	return release.Candidate{}, nil
}

func (memoryStore) BundleOf(context.Context, uint64, string, string) (release.Bundle, error) {
	return release.Bundle{}, nil
}

func (memoryStore) Head(context.Context, uint64, string) (release.Head, error) {
	return release.Head{}, nil
}

func (memoryStore) MembersOf(context.Context, uint64, string, string) (map[string]string, error) {
	return nil, nil
}

// receive submits a one-member bundle citing ref and reports whether it was accepted.
func receive(t *testing.T, e *Evidence, tenant uint64, space, ref string) (bool, error) {
	t.Helper()
	s := release.NewService(memoryStore{}, e, map[string][]byte{"candidate_bundle": []byte(testSchema)})
	raw := rawBundle(t, "", "a", `{"v":1}`)
	raw = []byte(strings.Replace(string(raw), "source:v1:k-1:1:abc", ref, 1))
	_, err := s.Receive(context.Background(), release.Principal{TenantID: tenant, Subject: "svc"}, space, raw)
	var failure *release.Error
	if errors.As(err, &failure) && failure.Code == release.ErrorCandidateInvalid {
		return false, nil
	}
	return err == nil, err
}

func TestEvidenceResolvesOnlyFixedRevisionsOfTheSpaceRawKB(t *testing.T) {
	e := resolver(t, nil)
	ok, err := receive(t, e, 7, "space-1", "source:v1:k-1:2:"+fileSHA)
	require.NoError(t, err)
	require.True(t, ok)

	for name, probe := range map[string]struct {
		tenant uint64
		space  string
		ref    string
	}{
		"other attempt":      {7, "space-1", "source:v1:k-1:3:" + fileSHA},
		"other fingerprint":  {7, "space-1", "source:v1:k-1:2:" + strings.Repeat("cd", 32)},
		"other raw KB":       {7, "space-1", "source:v1:k-other:1:" + fileSHA},
		"other tenant":       {8, "space-1", "source:v1:k-1:2:" + fileSHA},
		"unconfigured Space": {7, "space-9", "source:v1:k-1:2:" + fileSHA},
		"unknown scheme":     {7, "space-1", "expert:v1:k-1:2:" + fileSHA},
		"malformed":          {7, "space-1", "source:v1:k-1:0:" + fileSHA},
	} {
		t.Run(name, func(t *testing.T) {
			ok, err := receive(t, e, probe.tenant, probe.space, probe.ref)
			require.NoError(t, err)
			require.False(t, ok)
		})
	}
}

func TestEvidenceFailsClosedWithoutScopeOrOnStorageErrors(t *testing.T) {
	_, err := resolver(t, nil).Resolve(context.Background(), "source:v1:k-1:2:"+fileSHA)
	require.Error(t, err, "outside Service.Receive there is no authenticated scope")
	// Receive turns any resolver error into a rejected bundle (S3b), never an acceptance.
	ok, err := receive(t, resolver(t, errors.New("database down")), 7, "space-1", "source:v1:k-1:2:"+fileSHA)
	require.NoError(t, err)
	require.False(t, ok)
}
