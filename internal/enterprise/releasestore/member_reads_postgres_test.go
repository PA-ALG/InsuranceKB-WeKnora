package releasestore

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

func TestPostgresFixedReadsKeepHistoryAndMemberAuthority(t *testing.T) {
	for _, chunked := range []bool{false, true} {
		name := "legacy"
		if chunked {
			name = "chunks"
		}
		t.Run(name, func(t *testing.T) {
			db := openSchema(t)
			store := New(db, testSpaces(t))
			ctx := context.Background()
			if chunked {
				require.NoError(t, db.Exec(`INSERT INTO enterprise_member_scopes
 (tenant_id,space_id,raw_kb_id,wiki_kb_id,mode) VALUES (7,'space-1','raw-1','wiki-1','bridge')`).Error)
			}
			s := service(store)
			c, err := s.Receive(ctx, principal, "space-1", rawBundle(t, "", "alias/first",
				`{"logical_key":"actual/key","subject_ref":"subject-a","value":"first"}`))
			require.NoError(t, err)
			d, err := s.Decide(ctx, principal, "space-1", c.ID, approve)
			require.NoError(t, err)
			first, err := s.Activate(ctx, principal, "space-1", c.ID, d.ID)
			require.NoError(t, err)
			if chunked {
				scope, e := testSpaces(t).Scope(7, "space-1")
				require.NoError(t, e)
				require.NoError(t, store.storage.Backfill(ctx, db, scope, first.ID, 16<<20))
				require.NoError(t, store.storage.StartObservation(ctx, db, scope))
			}
			c, err = s.Receive(ctx, principal, "space-1", rawBundle(t, first.ID, "second", `{"value":"later"}`))
			require.NoError(t, err)
			d, err = s.Decide(ctx, principal, "space-1", c.ID, approve)
			require.NoError(t, err)
			second, err := s.Activate(ctx, principal, "space-1", c.ID, d.ID)
			require.NoError(t, err)

			type fixedReads interface {
				MemberIndex(context.Context, uint64, string, string) (release.Release, []release.Member, error)
				LookupMembers(context.Context, uint64, string, string, []string) (release.Release, []release.Member, error)
			}
			narrow, ok := any(store).(fixedReads)
			require.True(t, ok, "production store needs fixed member reads")
			head, index, err := narrow.MemberIndex(ctx, 7, "space-1", first.ID)
			require.NoError(t, err)
			require.NotEqual(t, second.ID, head.ID)
			require.Equal(t, first.ID, head.ID)
			require.Len(t, index, 1)
			require.Equal(t, first.Members[0].MemberDigest, index[0].MemberDigest)
			require.JSONEq(t, `{"logical_key":"actual/key","subject_ref":"subject-a"}`, string(index[0].Payload))
			_, members, err := narrow.LookupMembers(ctx, 7, "space-1", first.ID, []string{"alias/first", "second"})
			require.NoError(t, err)
			require.Equal(t, first.Members, members)
			_, _, err = narrow.MemberIndex(ctx, 7, "space-2", first.ID)
			require.Error(t, err)
			changed := db.Exec(`UPDATE wiki_release_preparations SET manifest = jsonb_set(manifest,
 '{candidate_id}', '"other"') WHERE preparation_id=(SELECT preparation_id FROM wiki_releases WHERE release_id=?)`, first.ID)
			require.NoError(t, changed.Error)
			_, _, err = narrow.MemberIndex(ctx, 7, "space-1", first.ID)
			require.Error(t, err)
		})
	}
}
