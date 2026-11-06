package releasestore

import (
	"context"
	"encoding/binary"
	"fmt"
	"sort"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func rootChunks(t *testing.T, db *gorm.DB, id string) map[string]int {
	t.Helper()
	var row struct{ Blocks []byte }
	root := storageRoot(t, db, id)
	require.NoError(t, db.Table("enterprise_member_sets").Where("digest = ?", root).Take(&row).Error)
	require.Zero(t, len(row.Blocks)%36)
	out := map[string]int{}
	for offset := 0; offset < len(row.Blocks); offset += 36 {
		n := int(binary.BigEndian.Uint32(row.Blocks[offset : offset+4]))
		require.LessOrEqual(t, n, 128)
		if offset+36 < len(row.Blocks) {
			require.GreaterOrEqual(t, n, 32)
		}
		out[string(row.Blocks[offset+4:offset+36])] = n
	}
	return out
}

func TestPostgresMemberStorageLocalBoundariesAndScatteredChanges(t *testing.T) {
	for _, n := range []int{0, 1, 31, 32, 33, 127, 128, 129, 1000} {
		t.Run(fmt.Sprint(n), func(t *testing.T) {
			db := memberStorageDB(t)
			referenceFixtureScope(t, db)
			store := New(db, testSpaces(t))
			base := storageMembers(t, n, 0)
			initial := storagePublish(t, store, "boundary-initial", base)
			rootChunks(t, db, initial.ID)
			for step, position := range []int{0, n / 2, n} {
				extended := append([]release.Member(nil), base...)
				entry := storageMembers(t, 1, 9)[0]
				entry.LogicalSlug = fmt.Sprintf("group/%06d-insert", position)
				if step == 0 {
					entry.LogicalSlug = "group/!front"
				}
				// Sorting is the production materialize contract, not insertion command order.
				extended = append(extended, entry)
				sort.Slice(extended, func(i, j int) bool { return extended[i].LogicalSlug < extended[j].LogicalSlug })
				before := logicalStorageBytes(t, db)
				after := storagePublish(t, store, fmt.Sprintf("insert-%d", step), extended)
				rootChunks(t, db, after.ID)
				changedBytes := logicalStorageBytes(t, db).Chunks - before.Chunks
				require.LessOrEqual(t, changedBytes, int64((1+4*128)*32+20*128))
				storagePublish(t, store, fmt.Sprintf("delete-%d", step), base)
			}
			got, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", "")
			require.NoError(t, err)
			require.Equal(t, base, got.Members)
		})
	}
	t.Run("scattered", func(t *testing.T) {
		db := memberStorageDB(t)
		referenceFixtureScope(t, db)
		store := New(db, testSpaces(t))
		scale := storageAcceptanceScale(t)
		base := storageMembers(t, scale.sizes[1], 0)
		first := storagePublish(t, store, "scatter-first", base)
		old := rootChunks(t, db, first.ID)
		for j := 0; j < 125; j++ {
			stride := 299
			if scale.sizes[1] == 3750 {
				stride = 30
			}
			i := j * stride
			base[i].Payload = []byte(`{"value":9}`)
			base[i].MemberDigest = memberDigest(t, string(base[i].Payload))
		}
		next := storagePublish(t, store, "scatter-next", base)
		chunks := rootChunks(t, db, next.ID)
		newCount, rewritten := 0, 0
		for digest, count := range chunks {
			if _, same := old[digest]; !same {
				newCount++
				rewritten += count
			}
		}
		require.LessOrEqual(t, newCount, 125)
		require.LessOrEqual(t, rewritten, 125*128)
	})
}
