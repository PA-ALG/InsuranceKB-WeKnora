package memberstore

import (
	"encoding/json"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func memoControlDB(t *testing.T) (*gorm.DB, sqlmock.Sqlmock) {
	t.Helper()
	conn, mock, err := sqlmock.New()
	require.NoError(t, err)
	t.Cleanup(func() {
		require.NoError(t, mock.ExpectationsWereMet())
		_ = conn.Close()
	})
	db, err := gorm.Open(postgres.New(postgres.Config{Conn: conn}), &gorm.Config{
		DisableAutomaticPing: true, Logger: logger.Default.LogMode(logger.Silent),
	})
	require.NoError(t, err)
	return db, mock
}

func memoControlWrite() (types.WikiReleaseMemberSetWrite, contentRow, []layoutChunk) {
	input := types.WikiReleaseMemberSnapshot{
		Kind: "page", LogicalSlug: "m/000001", RevisionID: "revision",
		MemberDigest: "business-digest", Title: "title", Content: "content",
		Payload: json.RawMessage(`{"n":9007199254740993,"v":1}`),
	}
	w := types.WikiReleaseMemberSetWrite{
		Scope: memoMemoryScope(), ReleaseID: "parent", Members: []types.WikiReleaseMemberSnapshot{input},
	}
	canonical := input
	canonical.Payload = json.RawMessage(`{"n": 9007199254740993, "v": 1}`)
	row := encodeContent(1, canonical)
	parent := []layoutChunk{{Entries: []layoutEntry{{Slug: row.LogicalSlug, Digest: row.Digest}}}}
	return w, row, parent
}

func expectMemoProjection(mock sqlmock.Sqlmock, canonical string) {
	mock.ExpectQuery("SELECT value::text AS value FROM jsonb_array_elements").
		WillReturnRows(sqlmock.NewRows([]string{"value"}).AddRow(canonical))
}

func expectMemoStoredCheck(mock sqlmock.Sqlmock, bad int) {
	mock.ExpectQuery("WITH wanted AS").
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(bad))
}

func TestComputationMemoRequiresAllSevenExactRawFields(t *testing.T) {
	tests := []struct {
		name   string
		change func(*types.WikiReleaseMemberSnapshot)
	}{
		{"kind", func(m *types.WikiReleaseMemberSnapshot) { m.Kind += "x" }},
		{"slug", func(m *types.WikiReleaseMemberSnapshot) { m.LogicalSlug += "x" }},
		{"revision", func(m *types.WikiReleaseMemberSnapshot) { m.RevisionID += "x" }},
		{"member_digest", func(m *types.WikiReleaseMemberSnapshot) { m.MemberDigest += "x" }},
		{"title", func(m *types.WikiReleaseMemberSnapshot) { m.Title += "x" }},
		{"content", func(m *types.WikiReleaseMemberSnapshot) { m.Content += "x" }},
		{"framed_metadata_boundaries", func(m *types.WikiReleaseMemberSnapshot) {
			m.MemberDigest = "business-diges"
			m.Title = "ttitle"
		}},
		{"raw_payload_whitespace", func(m *types.WikiReleaseMemberSnapshot) {
			m.Payload = json.RawMessage(`{ "n":9007199254740993,"v":1 }`)
		}},
		{"raw_payload_key_order", func(m *types.WikiReleaseMemberSnapshot) {
			m.Payload = json.RawMessage(`{"v":1,"n":9007199254740993}`)
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			db, mock := memoControlDB(t)
			w, row, parent := memoControlWrite()
			store := New()
			store.rememberComputations(w, []contentRow{row})
			w.ParentReleaseID, w.ReleaseID = w.ReleaseID, "next"
			test.change(&w.Members[0])
			expectMemoProjection(mock, row.PayloadJSON)
			all, changed, err := store.computedContents(db, 1, w, parent)
			require.NoError(t, err)
			require.Len(t, changed, 1, "a changed raw field must be canonicalized even if its projection is unchanged")
			require.Equal(t, changed, all)
			expected := w.Members[0]
			expected.Payload = json.RawMessage(row.PayloadJSON)
			require.Equal(t, encodeContent(1, expected), changed[0])
		})
	}
}

func TestComputationMemoRawAndCanonicalPayloadIdentitiesStayDistinct(t *testing.T) {
	db, mock := memoControlDB(t)
	w, row, parent := memoControlWrite()
	store := New()
	store.rememberComputations(w, []contentRow{row})
	w.ParentReleaseID, w.ReleaseID = w.ReleaseID, "next"
	expectMemoStoredCheck(mock, 0)
	all, changed, err := store.computedContents(db, 1, w, parent)
	require.NoError(t, err)
	require.Empty(t, changed, "identical raw input reuses a canonical digest containing different whitespace")
	require.Equal(t, row.Digest, all[0].Digest)
	require.Equal(t, row.LogicalSlug, all[0].LogicalSlug)
	// The memo must own hashes rather than borrow the caller's mutable raw bytes.
	w.Members[0].Payload[5] = '8'
	expectMemoProjection(mock, `{"n": 8007199254740993, "v": 1}`)
	_, changed, err = store.computedContents(db, 1, w, parent)
	require.NoError(t, err)
	require.Len(t, changed, 1)
	require.NotEqual(t, row.Digest, changed[0].Digest)
}

func TestComputationMemoScopeAndParentMustMatch(t *testing.T) {
	tests := []struct {
		name   string
		change func(*types.WikiReleaseMemberSetWrite, *[]layoutChunk)
	}{
		{"tenant", func(w *types.WikiReleaseMemberSetWrite, _ *[]layoutChunk) { w.Scope.TenantID++ }},
		{"space", func(w *types.WikiReleaseMemberSetWrite, _ *[]layoutChunk) { w.Scope.SpaceID += "x" }},
		{"raw_kb", func(w *types.WikiReleaseMemberSetWrite, _ *[]layoutChunk) { w.Scope.RawKBID += "x" }},
		{"wiki_kb", func(w *types.WikiReleaseMemberSetWrite, _ *[]layoutChunk) { w.Scope.WikiKBID += "x" }},
		{"parent_id", func(w *types.WikiReleaseMemberSetWrite, _ *[]layoutChunk) { w.ParentReleaseID += "x" }},
		{"missing_parent_entry", func(_ *types.WikiReleaseMemberSetWrite, p *[]layoutChunk) { *p = nil }},
		{"different_parent_digest", func(_ *types.WikiReleaseMemberSetWrite, p *[]layoutChunk) {
			(*p)[0].Entries[0].Digest = make([]byte, 32)
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			db, mock := memoControlDB(t)
			w, row, parent := memoControlWrite()
			store := New()
			store.rememberComputations(w, []contentRow{row})
			w.ParentReleaseID, w.ReleaseID = w.ReleaseID, "next"
			test.change(&w, &parent)
			expectMemoProjection(mock, row.PayloadJSON)
			all, changed, err := store.computedContents(db, 1, w, parent)
			require.NoError(t, err)
			require.Len(t, changed, 1)
			require.Equal(t, all, changed)
		})
	}
}

func TestComputationMemoRechecksPreimagesAfterRolledBackWrite(t *testing.T) {
	db, mock := memoControlDB(t)
	w, row, parent := memoControlWrite()
	store := New()
	// A caller may remember before the outer transaction is rolled back. A memo
	// remains computation only, including if a subsequent parent index matches.
	store.rememberComputations(w, []contentRow{row})
	w.ParentReleaseID, w.ReleaseID = w.ReleaseID, "next"
	expectMemoStoredCheck(mock, 1)
	all, changed, err := store.computedContents(db, 1, w, parent)
	require.ErrorIs(t, err, ErrIntegrity)
	require.Nil(t, all)
	require.Nil(t, changed)
}
