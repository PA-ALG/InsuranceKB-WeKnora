package chatsource

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

type admissionSpaces struct{}

func (admissionSpaces) SpaceOf(tenant uint64, kb string) (string, Role, bool) {
	if (tenant == 7 || tenant == 8) && (kb == "raw" || kb == "wiki") {
		role := RoleRaw
		if kb == "wiki" {
			role = RoleWiki
		}
		return "space", role, true
	}
	return "", "", false
}

type admissionKBs struct {
	interfaces.KnowledgeBaseService
	rows    map[string]*types.KnowledgeBase
	checked []string
	deny    error
}

func (k *admissionKBs) GetKnowledgeBaseByIDOnly(_ context.Context, id string) (*types.KnowledgeBase, error) {
	return k.rows[id], nil
}

func (k *admissionKBs) CheckNativeRead(_ context.Context, id string) error {
	k.checked = append(k.checked, id)
	return k.deny
}

type admissionDocs []*types.Knowledge

func (d admissionDocs) GetKnowledgeBatchWithSharedAccess(
	context.Context, uint64, []string,
) ([]*types.Knowledge, error) {
	return d, nil
}

type admissionDirectory struct{ admissionSpaces }

func (admissionDirectory) SpaceOwner(kb string) (uint64, string, Role, bool) {
	if kb == "raw" || kb == "wiki" {
		return 7, "space", RoleRaw, true
	}
	if kb == "foreign-raw" {
		return 8, "foreign-space", RoleRaw, true
	}
	return 0, "", "", false
}

type admissionDocumentLookup struct {
	rows     []*types.Knowledge
	metadata map[string]*types.Knowledge
	err      error
}

func (d admissionDocumentLookup) GetKnowledgeBatchWithSharedAccess(
	context.Context, uint64, []string,
) ([]*types.Knowledge, error) {
	return d.rows, d.err
}

func (d admissionDocumentLookup) GetKnowledgeByIDOnly(_ context.Context, id string) (*types.Knowledge, error) {
	return d.metadata[id], nil
}

func TestAdmissionEnterpriseExceptionKeepsOtherManagedPolicy(t *testing.T) {
	r := NewResolver(admissionSpaces{}, nil, nil, nil)
	blocked := &managed.ReadError{Code: managed.ErrorCodeReleaseManaged}
	kbs := &admissionKBs{rows: map[string]*types.KnowledgeBase{
		"raw": {ID: "raw", TenantID: 7}, "other": {ID: "other", TenantID: 7},
	}, deny: blocked}
	_, err := PrepareSelection(context.Background(), r, kbs, nil, 7, []string{"raw"}, nil, nil, true)
	require.NoError(t, err)
	require.Empty(t, kbs.checked)
	_, err = PrepareSelection(context.Background(), r, kbs, nil, 7, []string{"raw", "other"}, nil, nil, true)
	require.ErrorIs(t, err, blocked)
	require.Equal(t, []string{"other"}, kbs.checked)
}

func TestAdmissionRejectsForeignEnterpriseAndIncompleteDocuments(t *testing.T) {
	r := NewResolver(admissionSpaces{}, nil, nil, nil)
	kbs := &admissionKBs{rows: map[string]*types.KnowledgeBase{"raw": {ID: "raw", TenantID: 8}}}
	_, err := PrepareSelection(context.Background(), r, kbs, nil, 7, []string{"raw"}, nil, nil, false)
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, "RELEASE_ACCESS_DENIED", failure.Code)
	kbs.rows["raw"].TenantID = 7
	_, err = PrepareSelection(context.Background(), r, kbs,
		admissionDocs{{ID: "one", KnowledgeBaseID: "raw", TenantID: 7}},
		7, nil, []string{"one", "missing"}, nil, false)
	require.Error(t, err)
}

func TestAdmissionBatchesAndResolvedScopeCannotSilentlyLoseEnterprise(t *testing.T) {
	r := NewResolver(admissionSpaces{}, nil, nil, nil)
	kbs := &admissionKBs{rows: map[string]*types.KnowledgeBase{"raw": {ID: "raw", TenantID: 7}}}
	sel, err := PrepareSelection(context.Background(), r, kbs,
		admissionDocs{{ID: "one", KnowledgeBaseID: "raw", TenantID: 7}},
		7, []string{"raw"}, []string{"one"}, nil, false)
	require.NoError(t, err)
	require.Error(t, sel.CheckKBs([]string{"raw"}, nil, nil))
	require.Error(t, sel.CheckDocuments([]string{"one"}, nil, nil))
	require.Error(t, sel.CheckTargets(nil))
	require.NoError(t, sel.CheckTargets(types.SearchTargets{{KnowledgeBaseID: "raw", TenantID: 7}}))
	boom := errors.New("database unavailable")
	require.ErrorIs(t, sel.CheckKBs([]string{"raw"}, nil, boom), boom)
}

func TestAdmissionRawOnlyNeedsNoWikiAPIKeyGrant(t *testing.T) {
	r := NewResolver(admissionSpaces{}, nil, nil, nil)
	kbs := &admissionKBs{rows: map[string]*types.KnowledgeBase{
		"raw": {ID: "raw", TenantID: 7}, "wiki": {ID: "wiki", TenantID: 7},
	}}
	ctx := types.WithTenantAPIKeyScope(context.Background(), types.TenantAPIKeyScope{
		KnowledgeBaseIDs: types.StringArray{"raw"},
	})
	_, err := PrepareSelection(ctx, r, kbs, nil, 7, []string{"raw"}, nil, nil, false)
	require.NoError(t, err)
	_, err = PrepareSelection(ctx, r, kbs, nil, 7, []string{"wiki"}, nil, nil, false)
	require.Error(t, err)
}

func TestAdmissionAgentOrdinaryKBAddsNoLookupOrStrictBatch(t *testing.T) {
	r := NewResolver(admissionDirectory{}, nil, nil, nil)
	selection, err := PrepareSelection(context.Background(), r, nil, nil, 7,
		[]string{"ordinary"}, nil, []types.TagScope{{KnowledgeBaseID: "ordinary-tagged"}}, false)
	require.NoError(t, err)
	boom := errors.New("native lookup failed")
	require.NoError(t, selection.CheckKBs([]string{"ordinary", "ordinary-tagged"}, nil, boom))
	require.NoError(t, selection.CheckTargets(nil))
	_, err = PrepareSelection(context.Background(), r, nil, nil, 7, []string{"raw"}, nil, nil, false)
	require.Error(t, err, "configured enterprise KB cannot skip incomplete metadata")
	_, err = PrepareSelection(context.Background(), r, nil, nil, 7, []string{"foreign-raw"}, nil, nil, false)
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, "RELEASE_ACCESS_DENIED", failure.Code)
}

func TestAdmissionAgentOrdinaryDocumentCanKeepNativePartialBehavior(t *testing.T) {
	r := NewResolver(admissionDirectory{}, nil, nil, nil)
	plain := &types.Knowledge{ID: "plain", TenantID: 7, KnowledgeBaseID: "ordinary"}
	boom := errors.New("partial batch failure")
	for _, docs := range []admissionDocumentLookup{
		{rows: []*types.Knowledge{plain}, err: boom},
		{metadata: map[string]*types.Knowledge{"plain": plain}, err: boom},
		{metadata: map[string]*types.Knowledge{"plain": plain}},
	} {
		selection, err := PrepareSelection(context.Background(), r, nil, docs, 7, nil, []string{"plain"}, nil, false)
		require.NoError(t, err)
		require.NoError(t, selection.CheckDocuments([]string{"plain"}, nil, boom))
		require.NoError(t, selection.CheckTargets(nil))
	}
}

func TestAdmissionAgentUnclassifiedAndEnterpriseDocumentsStayClosed(t *testing.T) {
	r := NewResolver(admissionDirectory{}, nil, nil, nil)
	enterprise := &types.Knowledge{ID: "enterprise", TenantID: 7, KnowledgeBaseID: "raw"}
	boom := errors.New("partial batch failure")
	for _, docs := range []admissionDocumentLookup{
		{err: boom},
		{rows: []*types.Knowledge{enterprise}, err: boom},
		{metadata: map[string]*types.Knowledge{"enterprise": enterprise}},
	} {
		_, err := PrepareSelection(context.Background(), r, nil, docs, 7, nil, []string{"enterprise"}, nil, false)
		require.Error(t, err)
	}
}
