package managed

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

type readClassifier struct {
	role    Role
	err     error
	tenants []uint64
}

func (c *readClassifier) Classify(_ context.Context, tenant uint64, _ string) (Role, error) {
	c.tenants = append(c.tenants, tenant)
	return c.role, c.err
}

type readKBs struct {
	interfaces.KnowledgeBaseService
	kb *types.KnowledgeBase
}

func (s *readKBs) GetKnowledgeBaseByIDOnly(context.Context, string) (*types.KnowledgeBase, error) {
	return s.kb, nil
}

type readDocuments struct {
	interfaces.KnowledgeService
	docs []*types.Knowledge
	err  error
}

func (s *readDocuments) GetKnowledgeBatchWithSharedAccess(context.Context, uint64, []string) ([]*types.Knowledge, error) {
	return s.docs, s.err
}

func TestCheckReadClassification(t *testing.T) {
	for _, tc := range []struct {
		name string
		role Role
		code string
	}{
		{"raw pending", Role{Kind: KindRaw, State: StatePending}, ErrorCodeReleaseManaged},
		{"wiki active", Role{Kind: KindWiki, State: StateActive}, ErrorCodeReleaseManaged},
		{"plain", Role{Kind: KindNone, State: StateUnmanaged}, ""},
		{"invalid", Role{Kind: "unexpected"}, ErrorCodeClassificationUnavailable},
	} {
		t.Run(tc.name, func(t *testing.T) {
			err := CheckRead(context.Background(), &readClassifier{role: tc.role}, 9, "library")
			if tc.code == "" {
				require.NoError(t, err)
			} else {
				var denial *ReadError
				require.ErrorAs(t, err, &denial)
				require.Equal(t, tc.code, denial.Code)
			}
		})
	}
	for _, c := range []Classifier{nil, &readClassifier{err: errors.New("private")}} {
		err := CheckRead(context.Background(), c, 9, "library")
		require.ErrorContains(t, err, ErrorCodeClassificationUnavailable)
		require.NotContains(t, err.Error(), "private")
	}
}

func TestSearchReadChecksAllSelectionsUnderOwner(t *testing.T) {
	for _, selection := range []string{"kb", "document", "tag"} {
		t.Run(selection, func(t *testing.T) {
			c := &readClassifier{role: Role{Kind: KindRaw, State: StatePending}}
			kb := DecorateKnowledgeBaseService(&readKBs{kb: &types.KnowledgeBase{ID: "library", TenantID: 9}}, c)
			docs := &readDocuments{docs: []*types.Knowledge{{ID: "document", KnowledgeBaseID: "library", TenantID: 9}}}
			var kbIDs, docIDs []string
			var tags []types.TagScope
			switch selection {
			case "kb":
				kbIDs = []string{"library"}
			case "document":
				docIDs = []string{"document"}
			case "tag":
				tags = []types.TagScope{{KnowledgeBaseID: "library"}}
			}
			err := CheckSearchRead(context.Background(), kb, docs, 1, kbIDs, docIDs, tags)
			require.ErrorContains(t, err, ErrorCodeReleaseManaged)
			require.Equal(t, []uint64{9}, c.tenants)
		})
	}
}
func TestSearchReadFailsClosedOnMissingDocumentsOrPolicy(t *testing.T) {
	c := &readClassifier{role: Role{Kind: KindNone, State: StateUnmanaged}}
	plain := &readKBs{kb: &types.KnowledgeBase{ID: "library", TenantID: 1}}
	decorated := DecorateKnowledgeBaseService(plain, c)
	require.ErrorContains(t, CheckSearchRead(context.Background(), plain, nil, 1, []string{"library"}, nil, nil), ErrorCodeClassificationUnavailable)
	require.ErrorContains(t, CheckSearchRead(context.Background(), decorated, &readDocuments{}, 1, nil, []string{"missing"}, nil), ErrorCodeClassificationUnavailable)
	require.NoError(t, CheckSearchRead(context.Background(), decorated, nil, 1, []string{"library", "library"}, nil, nil))
	require.NoError(t, CheckSearchRead(context.Background(), plain, nil, 1, nil, nil, nil))
}
