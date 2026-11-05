package releasestore

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestPostgresMemberStoragePublicTransactionSharesRootAndReplays(t *testing.T) {
	db := memberStorageDB(t)
	store := New(db, testSpaces(t))
	s := service(store)
	ctx := context.Background()
	raw := rawBundle(t, "", "synthetic/value", `{"value": "原字節", "number":9007199254740993}`)
	c, err := s.Receive(ctx, principal, "space-1", raw)
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal, "space-1", c.ID, approve)
	require.NoError(t, err)
	r, err := s.Activate(ctx, principal, "space-1", c.ID, d.ID)
	require.NoError(t, err)
	require.EqualValues(t, 1, storageCount(t, db, "enterprise_member_releases"), "production activation must write a member root")
	root := storageRoot(t, db, r.ID)
	var prep struct{ RootDigest []byte }
	require.NoError(t, db.Table("enterprise_member_preparations").Take(&prep).Error)
	require.Equal(t, root, prep.RootDigest)
	require.EqualValues(t, 1, storageCount(t, db, "enterprise_member_contents"))
	fixtureReferenceReads(t, db)
	got, err := service(New(db, testSpaces(t))).Release(ctx, principal, "space-1", r.ID)
	require.NoError(t, err)
	require.Equal(t, r.Members, got.Members)
	again, err := s.Activate(ctx, principal, "space-1", c.ID, d.ID)
	require.NoError(t, err)
	require.Equal(t, r.ID, again.ID)
	require.EqualValues(t, 1, storageCount(t, db, "wiki_release_heads"))
	require.EqualValues(t, 1, storageCount(t, db, "wiki_release_receipts"))
}

func TestPostgresMemberStorageSevenFieldsAndScopeAreIdentity(t *testing.T) {
	db := memberStorageDB(t)
	repo := New(db, testSpaces(t)).releases
	scope, err := testSpaces(t).Scope(7, "space-1")
	require.NoError(t, err)
	original := types.WikiReleaseMemberSnapshot{Kind: "page", LogicalSlug: "generic/value", RevisionID: "v1", MemberDigest: fileSHA, Title: "title", Content: "正文原字節", Payload: json.RawMessage(`{"number":9007199254740993}`)}
	fields := []func(*types.WikiReleaseMemberSnapshot){
		func(m *types.WikiReleaseMemberSnapshot) { m.Kind = "claim" }, func(m *types.WikiReleaseMemberSnapshot) { m.LogicalSlug = "generic/new" },
		func(m *types.WikiReleaseMemberSnapshot) { m.RevisionID = "v2" }, func(m *types.WikiReleaseMemberSnapshot) { m.Title = "new title" },
		func(m *types.WikiReleaseMemberSnapshot) { m.Content = "different envelope" }, func(m *types.WikiReleaseMemberSnapshot) { m.MemberDigest = strings.Repeat("a", 64) },
		func(m *types.WikiReleaseMemberSnapshot) { m.Payload = json.RawMessage(`{"number":9007199254740994}`) },
	}
	for i, change := range append([]func(*types.WikiReleaseMemberSnapshot){func(*types.WikiReleaseMemberSnapshot) {}}, fields...) {
		m := original
		change(&m)
		repositoryStorageWrite(t, repo, scope, fmt.Sprintf("identity-%d", i), []types.WikiReleaseMemberSnapshot{m})
		require.EqualValues(t, i+1, storageCount(t, db, "enterprise_member_contents"), "all seven fields participate")
	}
	other, err := testSpaces(t).Scope(7, "space-2")
	require.NoError(t, err)
	repositoryStorageWrite(t, repo, other, "other-scope", []types.WikiReleaseMemberSnapshot{original})
	require.EqualValues(t, 2, storageCount(t, db, "enterprise_member_scopes"))
	require.EqualValues(t, 9, storageCount(t, db, "enterprise_member_contents"))
}

func TestPostgresMemberStorageNeverFallsBackFromCorruptReferences(t *testing.T) {
	for _, target := range []string{"mapping", "root", "chunk", "content", "scope", "hash"} {
		t.Run(target, func(t *testing.T) {
			db := memberStorageDB(t)
			r := storagePublish(t, New(db, testSpaces(t)), "damage", storageMembers(t, 70, 1))
			require.EqualValues(t, 1, storageCount(t, db, "enterprise_member_releases"))
			fixtureReferenceReads(t, db)
			switch target {
			case "mapping":
				require.NoError(t, db.Exec(`DELETE FROM enterprise_member_releases`).Error)
			case "root":
				require.NoError(t, db.Exec(`UPDATE enterprise_member_sets SET blocks=decode(repeat('00',octet_length(blocks)),'hex')`).Error)
			case "chunk":
				require.NoError(t, db.Exec(`DELETE FROM enterprise_member_chunks`).Error)
			case "content":
				require.NoError(t, db.Exec(`DELETE FROM enterprise_member_contents`).Error)
			case "scope":
				// The fixed scope itself is changed; no FK bypass or cross-scope row corruption.
				break
			case "hash":
				require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET title='tampered'`).Error)
			}
			spaces := testSpaces(t)
			if target == "scope" {
				var parseErr error
				spaces, parseErr = ParseSpaces(`[{"tenant_id":7,"space_id":"space-1","raw_kb_id":"other-raw","wiki_kb_id":"wiki-1"}]`)
				require.NoError(t, parseErr)
			}
			_, err := New(db, spaces).ReleaseByID(context.Background(), 7, "space-1", r.ID)
			require.Error(t, err, "a retained legacy copy must not conceal broken ref-only storage")
			require.Positive(t, storageCount(t, db, "wiki_release_members"), "legacy fallback bait remains")
		})
	}
}

func TestPostgresMemberStorageConflictRollsBackOriginalHead(t *testing.T) {
	db := memberStorageDB(t)
	store := New(db, testSpaces(t))
	r := storagePublish(t, store, "first", storageMembers(t, 40, 1))
	require.EqualValues(t, 1, storageCount(t, db, "enterprise_member_releases"))
	require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET title='tampered'`).Error)
	before := fullStorageCounts(t, db)
	w := activation(t, store, "conflict")
	w.Members = storageMembers(t, 40, 1)
	_, err := store.Activate(context.Background(), w)
	require.Error(t, err)
	require.Equal(t, before, fullStorageCounts(t, db))
	head, err := store.Head(context.Background(), 7, "space-1")
	require.NoError(t, err)
	require.Equal(t, r.ID, head.ReleaseID)
}

func TestPostgresMemberStorageDifferentLayoutsRemainLogicallyEqual(t *testing.T) {
	db := memberStorageDB(t)
	store := New(db, testSpaces(t))
	m := storageMembers(t, 640, 1)
	next := 0
	for i := range m {
		for {
			key := fmt.Sprintf("group/%06d", next)
			next++
			if !storageNaturalCut(key) {
				m[i].LogicalSlug = key
				break
			}
		}
	}
	first := storagePublish(t, store, "layout-first", m)
	root := storageRoot(t, db, first.ID)
	// An insertion/deletion changes the internal layout but not the final logical sequence.
	extra := release.Member{Kind: "claim", LogicalSlug: m[50].LogicalSlug + "a", Payload: json.RawMessage(`{"value":3}`), MemberDigest: memberDigest(t, `{"value":3}`)}
	for storageNaturalCut(extra.LogicalSlug) {
		extra.LogicalSlug += "a"
	}
	intermediate := append(append([]release.Member(nil), m[:51]...), extra)
	intermediate = append(intermediate, m[51:]...)
	storagePublish(t, store, "layout-insert", intermediate)
	last := storagePublish(t, store, "layout-delete", m)
	require.NotEqual(t, root, storageRoot(t, db, last.ID), "fixture must actually produce two layouts")
	fixtureReferenceReads(t, db)
	require.NoError(t, db.Exec(`DELETE FROM wiki_release_members`).Error)
	a, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", first.ID)
	require.NoError(t, err)
	b, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", last.ID)
	require.NoError(t, err)
	require.Equal(t, a.Members, b.Members)
	// Frozen public preparation equality compares logical snapshots, not root digests.
	for _, id := range []string{first.ID, last.ID} {
		got, err := New(db, testSpaces(t)).MembersOf(context.Background(), 7, "space-1", id)
		require.NoError(t, err)
		require.Len(t, got, len(m))
	}
}

func TestPostgresMemberStorageMigration13IsPackaged(t *testing.T) {
	_, file, _, _ := runtime.Caller(0)
	dir := filepath.Join(filepath.Dir(file), "../../../migrations/enterprise/versioned")
	for _, suffix := range []string{"up", "down"} {
		raw, err := os.ReadFile(filepath.Join(dir, "000013_enterprise_member_chunks."+suffix+".sql"))
		require.NoError(t, err)
		require.NotEmpty(t, raw)
	}
}

func TestPostgresMemberStoragePreservesSnapshotPayloadAndDefaultKind(t *testing.T) {
	db := memberStorageDB(t)
	m := storageMembers(t, 2, 1)
	m[0].Kind = ""
	r := storagePublish(t, New(db, testSpaces(t)), "default-kind", m)
	require.EqualValues(t, 1, storageCount(t, db, "enterprise_member_releases"))
	var p types.WikiReleasePreparation
	require.NoError(t, db.Take(&p).Error)
	rows := storedSnapshots(t, db, r.ID)
	require.Equal(t, rows, p.Members)
	require.Equal(t, "page", p.Members[0].Kind)
	fixtureReferenceReads(t, db)
	got, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", r.ID)
	require.NoError(t, err)
	require.Equal(t, r.Members, got.Members)
}

func storageNaturalCut(slug string) bool {
	var length [8]byte
	binary.BigEndian.PutUint64(length[:], uint64(len(slug)))
	h := sha256.New()
	h.Write([]byte("enterprise-member-boundary.v1\x00"))
	h.Write(length[:])
	h.Write([]byte(slug))
	sum := h.Sum(nil)
	return sum[7]&63 == 0
}
