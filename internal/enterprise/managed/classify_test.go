package managed

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

type headStub struct {
	heads map[string]*types.WikiReleaseHead
	err   error
}

func (s headStub) GetHeadForWikiKB(_ context.Context, _ uint64, kbID string) (*types.WikiReleaseHead, error) {
	if s.err != nil {
		return nil, s.err
	}
	if h := s.heads[kbID]; h != nil {
		return h, nil
	}
	return nil, repository.ErrWikiReleaseNotFound
}

type custodyStub struct {
	scopes []types.WikiReleaseScope
	err    error
}

func (s custodyStub) FindScopes(context.Context, uint64, string) ([]types.WikiReleaseScope, error) {
	return s.scopes, s.err
}

func TestClassifyBothRolesBeforeAndAfterActivation(t *testing.T) {
	scope := types.WikiReleaseScope{TenantID: 42, SpaceID: "space", WikiKBID: "wiki", RawKBID: "raw"}
	for _, state := range []State{StatePending, StateActive} {
		for _, tc := range []struct {
			kb   string
			kind Kind
		}{{"wiki", KindWiki}, {"raw", KindRaw}} {
			t.Run(string(state)+"/"+string(tc.kind), func(t *testing.T) {
				heads := headStub{}
				if state == StateActive {
					heads.heads = map[string]*types.WikiReleaseHead{"wiki": {
						WikiReleaseScope: scope, ActiveReleaseID: "release", ActivationEpoch: 1,
					}}
				}
				classifier := NewClassifier(heads, custodyStub{scopes: []types.WikiReleaseScope{scope}})
				role, err := classifier.Classify(context.Background(), 42, tc.kb)
				require.NoError(t, err)
				require.Equal(t, tc.kind, role.Kind)
				require.Equal(t, state, role.State)
				require.Equal(t, &scope, role.Scope)
			})
		}
	}
}

func TestClassifyUnmanagedAndWikiRolePriority(t *testing.T) {
	role, err := NewClassifier(headStub{}, custodyStub{}).Classify(context.Background(), 42, "ordinary")
	require.NoError(t, err)
	require.Equal(t, Role{Kind: KindNone, State: StateUnmanaged}, role)
	wiki := types.WikiReleaseScope{TenantID: 42, SpaceID: "space-a", WikiKBID: "both", RawKBID: "source"}
	raw := types.WikiReleaseScope{TenantID: 42, SpaceID: "space-b", WikiKBID: "published", RawKBID: "both"}
	for _, scopes := range [][]types.WikiReleaseScope{{raw, wiki}, {wiki, raw}} {
		role, err = NewClassifier(headStub{}, custodyStub{scopes: scopes}).Classify(context.Background(), 42, "both")
		require.NoError(t, err)
		require.Equal(t, KindWiki, role.Kind)
		require.Equal(t, &wiki, role.Scope)
	}
}

func TestClassifyFailsClosed(t *testing.T) {
	scope := types.WikiReleaseScope{TenantID: 42, SpaceID: "space", WikiKBID: "wiki", RawKBID: "raw"}
	for _, tc := range []struct {
		name    string
		heads   HeadLookup
		custody CustodyLookup
		tenant  uint64
		kb      string
	}{
		{"tenant missing", headStub{}, custodyStub{}, 0, "wiki"},
		{"kb missing", headStub{}, custodyStub{}, 42, " "},
		{"head dependency missing", nil, custodyStub{}, 42, "wiki"},
		{"custody dependency missing", headStub{}, nil, 42, "wiki"},
		{"custody query failed", headStub{}, custodyStub{err: errors.New("lookup failed")}, 42, "wiki"},
		{
			"head query failed",
			headStub{err: errors.New("lookup failed")},
			custodyStub{scopes: []types.WikiReleaseScope{scope}},
			42, "wiki",
		},
		{"foreign custody", headStub{}, custodyStub{scopes: []types.WikiReleaseScope{
			{TenantID: 43, SpaceID: "space", WikiKBID: "wiki", RawKBID: "raw"},
		}}, 42, "wiki"},
		{"foreign head", headStub{heads: map[string]*types.WikiReleaseHead{"wiki": {
			WikiReleaseScope: types.WikiReleaseScope{
				TenantID: 43, SpaceID: "space", WikiKBID: "wiki", RawKBID: "raw",
			}, ActiveReleaseID: "release", ActivationEpoch: 1,
		}}}, custodyStub{scopes: []types.WikiReleaseScope{scope}}, 42, "wiki"},
		{
			"nil head without not-found",
			nilHeadLookup{},
			custodyStub{scopes: []types.WikiReleaseScope{scope}},
			42, "wiki",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, err := NewClassifier(tc.heads, tc.custody).Classify(context.Background(), tc.tenant, tc.kb)
			require.Error(t, err)
		})
	}
}

type nilHeadLookup struct{}

func (nilHeadLookup) GetHeadForWikiKB(context.Context, uint64, string) (*types.WikiReleaseHead, error) {
	return nil, nil
}

func TestCustodyLookupCoversEveryTableAndTenant(t *testing.T) {
	tables := []string{
		types.WikiReleaseHead{}.TableName(), types.WikiReleasePreparation{}.TableName(),
		types.WikiRelease{}.TableName(), types.WikiReleaseReceipt{}.TableName(),
	}
	for _, table := range tables {
		t.Run(table, func(t *testing.T) {
			db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
			require.NoError(t, err)
			conn, err := db.DB()
			require.NoError(t, err)
			t.Cleanup(func() { _ = conn.Close() })
			for _, name := range tables {
				require.NoError(t, db.Exec(fmt.Sprintf(
					"CREATE TABLE %s (tenant_id INTEGER, space_id TEXT, raw_kb_id TEXT, wiki_kb_id TEXT)", name,
				)).Error)
			}
			scope := types.WikiReleaseScope{TenantID: 42, SpaceID: "space", WikiKBID: "wiki", RawKBID: "raw"}
			require.NoError(t, db.Table(table).Create(&scope).Error)
			require.NoError(t, db.Table(table).Create(&scope).Error)
			lookup := NewCustodyLookup(db)
			for _, kb := range []string{"wiki", "raw"} {
				scopes, err := lookup.FindScopes(context.Background(), 42, kb)
				require.NoError(t, err)
				require.Equal(t, []types.WikiReleaseScope{scope}, scopes)
				scopes, err = lookup.FindScopes(context.Background(), 43, kb)
				require.NoError(t, err)
				require.Empty(t, scopes)
			}
		})
	}
}

func TestCustodyUnavailableIsAnError(t *testing.T) {
	_, err := NewCustodyLookup(nil).FindScopes(context.Background(), 42, "wiki")
	require.Error(t, err)
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	require.NoError(t, err)
	conn, err := db.DB()
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, conn.Close()) })
	_, err = NewCustodyLookup(db).FindScopes(context.Background(), 42, "wiki")
	require.Error(t, err, "missing custody table must never imply unmanaged")
}

func TestHeadCustodyAloneClassifiesWiki(t *testing.T) {
	scope := types.WikiReleaseScope{TenantID: 42, SpaceID: "space", WikiKBID: "wiki", RawKBID: "raw"}
	classifier := NewClassifier(headStub{heads: map[string]*types.WikiReleaseHead{"wiki": {
		WikiReleaseScope: scope, ActiveReleaseID: "release", ActivationEpoch: 1,
	}}}, custodyStub{})
	role, err := classifier.Classify(context.Background(), 42, "wiki")
	require.NoError(t, err)
	require.Equal(t, Role{Kind: KindWiki, State: StateActive, Scope: &scope}, role)
}

func TestDatabaseClassifierFailsClosedWithoutDatabase(t *testing.T) {
	_, err := NewDatabaseClassifier(nil).Classify(context.Background(), 42, "wiki")
	require.Error(t, err)
}
