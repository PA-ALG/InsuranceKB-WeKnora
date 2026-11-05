package releasestore

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func paddedStorageMember(t *testing.T, i, version int) release.Member {
	t.Helper()
	m := release.Member{Kind: "claim", LogicalSlug: fmt.Sprintf("group/%06d", i), AccessScope: "space"}
	makePayload := func(padding int, space string) {
		m.Payload = json.RawMessage(fmt.Sprintf(
			`{%s"value":"%06d/%06d%s"}`, space, i, version, strings.Repeat("x", padding),
		))
		m.MemberDigest = memberDigest(t, string(m.Payload))
	}
	makePayload(0, "")
	width := func() int {
		envelope, err := json.Marshal(memberEnvelope{
			Version: 1, Payload: string(m.Payload), AccessScope: m.AccessScope,
		})
		require.NoError(t, err)
		// PostgreSQL strips input whitespace, then inserts one space after the only key's colon.
		var compact bytes.Buffer
		require.NoError(t, json.Compact(&compact, m.Payload))
		return 8 + 32 + 4 + len(m.Kind) + len(m.LogicalSlug) + len(m.MemberDigest) + len(envelope) + compact.Len() + 1
	}
	padding := (5120 - width()) / 2
	makePayload(padding, "")
	if width() == 5119 {
		makePayload(padding, " ")
	}
	require.Equal(t, 5120, width())
	return m
}

func referenceFixtureScope(t *testing.T, db *gorm.DB) {
	t.Helper()
	// Controlled synthetic state; small operator acceptance tests lock the actual transition guard.
	require.NoError(t, db.Exec("INSERT INTO enterprise_member_scopes\n (tenant_id,space_id,raw_kb_"+
		"id,wiki_kb_id,mode,observation_started_at,observation_failure_since)\n VALUES(7,'space-1','r"+
		"aw-1','wiki-1','reference',CURRENT_TIMESTAMP-INTERVAL '8 days',CURRENT_TIMESTAMP)").Error)
}

type storageBytes struct{ Contents, Chunks, Roots, Mappings, Control int64 }

func logicalStorageBytes(t *testing.T, db *gorm.DB) storageBytes {
	t.Helper()
	var b storageBytes
	queries := []struct {
		out *int64
		sql string
	}{
		{&b.Contents, "SELECT COALESCE(sum(44+octet_length(kind)+octet_length(logical_sl" +
			"ug)+octet_length(revision_id)+octet_length(member_digest)+octet_l" +
			"ength(title)+octet_length(content)+octet_length(payload_json)),0)" +
			" FROM enterprise_member_contents"},
		{&b.Chunks, `SELECT COALESCE(sum(48+octet_length(refs)),0) FROM enterprise_member_chunks`},
		{&b.Roots, "SELECT COALESCE(sum(56+octet_length(order_mode)+octet_length(bloc" +
			"ks)),0) FROM enterprise_member_sets"},
		{&b.Control, "SELECT COALESCE(sum(40+CASE WHEN observation_failure_since IS NULL THEN 0 ELSE 8 END+octet_length(space_id)+octet_length(raw_kb" +
			"_id)+octet_length(wiki_kb_id)+octet_length(mode)),0) FROM enterpr" +
			"ise_member_scopes"},
	}
	for _, q := range queries {
		require.NoError(t, db.Raw(q.sql).Scan(q.out).Error)
	}
	for _, pair := range [][2]string{
		{"enterprise_member_releases", "release_id"}, {"enterprise_member_preparations", "preparation_id"},
	} {
		var n int64
		require.NoError(t, db.Raw(fmt.Sprintf("SELECT COALESCE(sum(49+octet_length(%s)+octet_length(space_id)+oc"+
			"tet_length(raw_kb_id)+octet_length(wiki_kb_id)),0) FROM %s", pair[1], pair[0])).Scan(&n).Error)
		b.Mappings += n
	}
	var n int64
	require.NoError(t, db.Raw("SELECT COALESCE(sum(48+octet_length(release_id)+octet_length(phas"+
		"e)),0) FROM enterprise_member_progress").Scan(&n).Error)
	b.Control += n
	for _, table := range []string{"enterprise_member_validation_pending", "enterprise_member_validation_failures"} {
		extra := ""
		if table == "enterprise_member_validation_failures" {
			extra = "+octet_length(kind)"
		}
		var bytes int64
		require.NoError(t, db.Raw("SELECT COALESCE(sum(16+octet_length(space_id)+octet_length(raw_kb_id)+octet_length(wiki_kb_id)+octet_length(attempt_id)"+extra+"),0) FROM "+table).Scan(&bytes).Error)
		b.Control += bytes
	}
	for _, table := range []string{"wiki_releases", "wiki_release_preparations"} {
		var markerBytes int64
		require.NoError(t, db.Raw("SELECT COALESCE(sum(octet_length(member_storage)),0) FROM "+table).
			Scan(&markerBytes).Error)
		b.Control += markerBytes
	}
	return b
}

func TestPostgresMemberStorageGrowthIndependentOfRemotePopulation(t *testing.T) {
	type delta struct{ content, chunk, root int64 }
	var measured []delta
	scale := storageAcceptanceScale(t)
	// Allocate the same two independent fixtures at the parent level. A missing
	// PG capability must stop the parent before its cross-case assertions.
	databases := []*gorm.DB{memberStorageDB(t), memberStorageDB(t)}
	for index, n := range scale.sizes {
		t.Run(fmt.Sprint(n), func(t *testing.T) {
			db := databases[index]
			referenceFixtureScope(t, db)
			store := New(db, testSpaces(t))
			// The larger version extends an identical prefix through ordinary publication.
			base := make([]release.Member, scale.sizes[0])
			for i := range base {
				base[i] = paddedStorageMember(t, i, 0)
			}
			first := storagePublish(t, store, "prefix", base)
			storageRoot(t, db, first.ID)
			if n > len(base) {
				for i := len(base); i < n; i++ {
					base = append(base, paddedStorageMember(t, i, 0))
				}
				storagePublish(t, store, "append-remote", base)
			}
			before := logicalStorageBytes(t, db)
			for i := scale.localStart; i < scale.localStart+125; i++ {
				base[i] = paddedStorageMember(t, i, 1)
			}
			storagePublish(t, store, "same-local-change", base)
			after := logicalStorageBytes(t, db)
			measured = append(measured, delta{
				after.Contents - before.Contents, after.Chunks - before.Chunks, after.Roots - before.Roots,
			})
			require.EqualValues(t, 125*5120, measured[len(measured)-1].content)
		})
	}
	require.Len(t, measured, 2)
	require.Equal(t, measured[0].content, measured[1].content)
	require.Equal(t, measured[0].chunk, measured[1].chunk)
	require.LessOrEqual(t, measured[1].root-measured[0].root, scale.rootDeltaLimit)
	t.Logf("sizes=%v local125 additions=%+v root-delta-limit=%d", scale.sizes, measured, scale.rootDeltaLimit)
}

func oldSerializedWidths(t *testing.T, db *gorm.DB) (memberColumns, prepItem int64) {
	t.Helper()
	var out struct{ Fields, Item int64 }
	require.NoError(t, db.Raw("SELECT\n octet_length(kind)+octet_length(logical_slug)+octet_lengt"+
		"h(revision_id)+octet_length(member_digest)+octet_length(title)+oc"+
		"tet_length(content)+octet_length(payload_json) AS fields,\n octet_"+
		"length(jsonb_build_object('kind',kind,'logical_slug',logical_slug"+
		",'revision_id',revision_id,\n 'member_digest',member_digest,'title"+
		"',title,'content',content,'payload',payload_json::jsonb)::text) A"+
		"S item\n FROM enterprise_member_contents LIMIT 1").Scan(&out).Error)
	require.EqualValues(t, 5120-44, out.Fields)
	// Original member IDs are release_id + ':' + slug; the original two ID columns are both counted.
	return out.Fields + 2*int64(len("rel_"+strings.Repeat("x", 32))) + 1 + int64(len("group/000000")), out.Item
}

func TestPostgresMemberStorageColdHistoriesAndStructureBudget(t *testing.T) {
	db := memberStorageDB(t)
	referenceFixtureScope(t, db)
	store := New(db, testSpaces(t))
	ctx := context.Background()
	type version struct {
		id        string
		n         int
		revisions [300]int
	}
	scale := storageAcceptanceScale(t)
	var versions []version
	var revisions [300]int
	var members []release.Member
	var oldMemberBytes, oldPreparationBytes, rowWidth, itemWidth int64
	publish := func(label string) {
		r := storagePublish(t, store, label, members)
		storageRoot(t, db, r.ID)
		versions = append(versions, version{r.ID, len(members), revisions})
		if rowWidth == 0 {
			rowWidth, itemWidth = oldSerializedWidths(t, db)
		}
		oldMemberBytes += int64(len(members)) * rowWidth
		oldPreparationBytes += 2 + int64(len(members))*itemWidth + int64(max(0, len(members)-1))*2
		if len(versions)%20 == 0 {
			checkStorageResourceBudget(t, db)
		}
	}
	for product := 0; product < scale.products; product++ {
		for field := 0; field < 125; field++ {
			members = append(members, paddedStorageMember(t, product*125+field, 0))
		}
		publish(fmt.Sprintf("append-%03d", product))
	}
	for round := 0; round < 10; round++ {
		for j := 0; j < scale.updatedPerRound; j++ {
			product := (round*scale.updatedPerRound + j) % scale.products
			revisions[product]++
			for field := 0; field < 125; field++ {
				i := product*125 + field
				members[i] = paddedStorageMember(t, i, revisions[product])
			}
			publish(fmt.Sprintf("round-%02d-%03d", round, product))
		}
	}
	require.Len(t, versions, scale.products+10*scale.updatedPerRound)
	b := logicalStorageBytes(t, db)
	structure := b.Chunks + b.Roots + b.Mappings + b.Control
	require.LessOrEqual(t, 10*structure, b.Contents, "count every structural logical column, not only blobs")
	require.Zero(t, storageCount(t, db, "wiki_release_members"), "large fixture cannot retain duplicate legacy bodies")
	var duplicatedPreparations int64
	require.NoError(t, db.Raw(`SELECT count(*) FROM wiki_release_preparations WHERE members <> '[]'::jsonb`).
		Scan(&duplicatedPreparations).Error)
	require.Zero(t, duplicatedPreparations, "reference-only must not retain a hidden second snapshot array")
	for _, v := range versions {
		// A fresh production adapter is an empty application/object cache for every history.
		got, err := New(db, testSpaces(t)).ReleaseByID(ctx, 7, "space-1", v.id)
		require.NoError(t, err)
		require.Len(t, got.Members, v.n)
		for i, m := range got.Members {
			require.Equal(t, paddedStorageMember(t, i, v.revisions[i/125]), m)
		}
		// Repository read compares every stored snapshot field and its order, not just serving projections.
		snapshots, err := New(db, testSpaces(t)).releases.GetReleaseMembers(ctx, mustStorageScope(t), v.id)
		require.NoError(t, err)
		expected, _, err := snapshotsOf(release.ActivationWrite{Members: got.Members})
		require.NoError(t, err)
		for i := range expected {
			var compact bytes.Buffer
			require.NoError(t, json.Compact(&compact, expected[i].Payload))
			expected[i].Payload = json.RawMessage(strings.Replace(compact.String(), `"value":`, `"value": `, 1))
		}
		require.Equal(t, expected, snapshots)
	}
	checkStorageResourceBudget(t, db)
	t.Logf("%d releases: content=%d structural=%d (chunks=%d roots=%d mappin"+
		"gs=%d control=%d); actual legacy columns=%d preparation-array-tex"+
		"t=%d", len(versions), b.Contents, structure, b.Chunks,
		b.Roots, b.Mappings, b.Control, oldMemberBytes, oldPreparationBytes)
}

func mustStorageScope(t *testing.T) types.WikiReleaseScope {
	t.Helper()
	scope, err := testSpaces(t).Scope(7, "space-1")
	require.NoError(t, err)
	return scope
}

func checkStorageResourceBudget(t *testing.T, db *gorm.DB) {
	t.Helper()
	var bytes int64
	require.NoError(t, db.Raw("SELECT pg_database_size(current_database())+(SELECT COALESCE(sum("+
		"size),0) FROM pg_ls_waldir())").Scan(&bytes).Error)
	require.Less(t, bytes, int64(2<<30), "stop this owned local fixture if DB+WAL exceeds the agreed resource cap")
	t.Logf("owned synthetic database+WAL=%d B", bytes)
}
