package memberstore

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"reflect"
	"sort"
	"testing"
)

// These keys exercise both hash extremes without relying on their real-world distribution.
func layoutKeys(count int, natural bool) []layoutEntry {
	entries := make([]layoutEntry, 0, count)
	for i := 0; len(entries) < count; i++ {
		slug := fmt.Sprintf("key-%08d", i)
		buf := append([]byte("enterprise-member-boundary.v1\x00"), make([]byte, 8)...)
		binary.BigEndian.PutUint64(buf[len(buf)-8:], uint64(len(slug)))
		h := sha256.Sum256(append(buf, []byte(slug)...))
		if (binary.BigEndian.Uint64(h[:8])&63 == 0) == natural {
			digest := sha256.Sum256([]byte(slug))
			entries = append(entries, layoutEntry{slug, digest[:]})
		}
	}
	return entries
}

func checkedLayout(t *testing.T, entries []layoutEntry, parent []layoutChunk) []layoutChunk {
	t.Helper()
	layout, err := buildLayout(entries, parent, "slug_asc")
	if err != nil {
		t.Fatal(err)
	}
	flat := make([]layoutEntry, 0, len(entries))
	for i, chunk := range layout {
		if len(chunk.Entries) < 1 || len(chunk.Entries) > 128 || (i < len(layout)-1 && len(chunk.Entries) < 32) {
			t.Fatalf("invalid block %d size %d", i, len(chunk.Entries))
		}
		flat = append(flat, chunk.Entries...)
	}
	if !reflect.DeepEqual(flat, entries) {
		t.Fatal("layout changed the final ordered entries")
	}
	return layout
}

func layoutSizes(chunks []layoutChunk) []int {
	sizes := make([]int, 0, len(chunks))
	for _, chunk := range chunks {
		sizes = append(sizes, len(chunk.Entries))
	}
	return sizes
}

func rewrittenEntries(parent, result []layoutChunk) int {
	previous := make(map[string]bool, len(parent))
	for _, chunk := range parent {
		previous[string(encodeChunk(1, chunk.Entries).Digest)] = true
	}
	count := 0
	for _, chunk := range result {
		if !previous[string(encodeChunk(1, chunk.Entries).Digest)] {
			count += len(chunk.Entries)
		}
	}
	return count
}

func requireBlocksShared(t *testing.T, parent, result []layoutChunk, indices []int) {
	t.Helper()
	digests := make(map[string]bool, len(result))
	for _, chunk := range result {
		digests[string(encodeChunk(1, chunk.Entries).Digest)] = true
	}
	for _, index := range indices {
		if !digests[string(encodeChunk(1, parent[index].Entries).Digest)] {
			t.Fatalf("block %d outside the edited window was rewritten", index)
		}
	}
}

func TestInitialLayoutThresholdsAndLegacySequence(t *testing.T) {
	for _, tc := range []struct {
		count   int
		natural bool
		sizes   []int
	}{{0, false, []int{}}, {31, true, []int{31}}, {
		100, true,
		[]int{32, 32, 32, 4},
	}, {273, false, []int{128, 128, 17}}} {
		entries := layoutKeys(tc.count, tc.natural)
		layout := checkedLayout(t, entries, nil)
		if !reflect.DeepEqual(layoutSizes(layout), tc.sizes) {
			t.Fatalf("initial layout %d: got %v, want %v", tc.count, layoutSizes(layout), tc.sizes)
		}
	}
	entries := layoutKeys(95, true)
	for left, right := 0, len(entries)-1; left < right; left, right = left+1, right-1 {
		entries[left], entries[right] = entries[right], entries[left]
	}
	layout, err := buildLayout(entries, nil, "legacy_sequence")
	if err != nil || !reflect.DeepEqual(layoutSizes(layout), []int{32, 32, 31}) {
		t.Fatalf("legacy sequence layout: %v %v", layoutSizes(layout), err)
	}
	var flat []layoutEntry
	for _, chunk := range layout {
		flat = append(flat, chunk.Entries...)
	}
	if !reflect.DeepEqual(entries, flat) {
		t.Fatal("legacy snapshot sequence reordered")
	}
}

func TestLayoutRejectsInvalidKeysDigestsAndParent(t *testing.T) {
	entries := layoutKeys(300, false)
	for _, tc := range []struct {
		name    string
		entries []layoutEntry
		parent  []layoutChunk
		mode    string
	}{
		{"mode", entries, nil, "other"},
		{"duplicate", []layoutEntry{entries[0], entries[0]}, nil, "slug_asc"},
		{"sequence duplicate", []layoutEntry{entries[0], entries[0]}, nil, "legacy_sequence"},
		{"order", []layoutEntry{entries[1], entries[0]}, nil, "slug_asc"},
		{"digest", []layoutEntry{{Slug: "a", Digest: []byte{1}}}, nil, "slug_asc"},
		{"empty parent block", entries, []layoutChunk{{}}, "slug_asc"},
		{"oversize parent", entries, []layoutChunk{{entries[:129]}, {entries[129:]}}, "slug_asc"},
		{"short internal parent", entries, []layoutChunk{{entries[:31]}, {entries[31:128]}}, "slug_asc"},
		{"parent order", entries, []layoutChunk{{[]layoutEntry{entries[1], entries[0]}}}, "slug_asc"},
		{"parent digest", entries, []layoutChunk{{[]layoutEntry{{Slug: "a"}}}}, "slug_asc"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := buildLayout(tc.entries, tc.parent, tc.mode); !errors.Is(err, ErrIntegrity) {
				t.Fatalf("invalid layout accepted: %v", err)
			}
		})
	}
}

func TestValueOnlyLayoutKeepsParentBoundariesAndAllowsDifferentHistories(t *testing.T) {
	entries := layoutKeys(241, false)
	parent := []layoutChunk{{entries[:32]}, {entries[32:96]}, {entries[96:224]}, {entries[224:]}}
	final := append([]layoutEntry(nil), entries...)
	for _, index := range []int{35, 200} {
		digest := sha256.Sum256([]byte("new-" + final[index].Slug))
		final[index].Digest = digest[:]
	}
	updated := checkedLayout(t, final, parent)
	if !reflect.DeepEqual(layoutSizes(updated), []int{32, 64, 128, 17}) {
		t.Fatal("value edits moved parent boundaries")
	}
	requireBlocksShared(t, parent, updated, []int{0, 3})
	if !reflect.DeepEqual(checkedLayout(t, final, updated), updated) {
		t.Fatal("no-op changed the maintained layout")
	}
	initial := checkedLayout(t, final, nil)
	if reflect.DeepEqual(initial, updated) || bytes.Equal(encodeSet(1, "slug_asc", layoutRows(initial)).
		Digest, encodeSet(1, "slug_asc", layoutRows(updated)).Digest) {
		t.Fatal("independent histories were incorrectly forced to one layout")
	}
	if !reflect.DeepEqual(checkedLayout(t, final, parent), updated) {
		t.Fatal("same parent and final sequence are not deterministic")
	}
}

func layoutRows(layout []layoutChunk) []chunkRow {
	rows := make([]chunkRow, 0, len(layout))
	for _, chunk := range layout {
		rows = append(rows, encodeChunk(1, chunk.Entries))
	}
	return rows
}

func TestKeyEditsRechunkOnlyProtectedWindowsAndRepairShortTail(t *testing.T) {
	entries := layoutKeys(12*128, false)
	parent := checkedLayout(t, entries, nil)
	for _, kind := range []string{"insert", "delete", "first", "tail", "separate"} {
		t.Run(kind, func(t *testing.T) {
			final := append([]layoutEntry(nil), entries...)
			shared := []int{0, 4, 5, 6, 7, 8, 9, 10, 11}
			switch kind {
			case "insert":
				for _, suffix := range []string{"!a", "!b", "!c"} {
					final = append(final, layoutEntry{entries[270].Slug + suffix, entries[270].Digest})
				}
			case "delete":
				final = append(final[:270:270], final[271:]...)
			case "first":
				final = append(final, layoutEntry{"!first", entries[0].Digest})
				shared = []int{2, 3, 4, 5, 6, 7, 8, 9, 10, 11}
			case "tail":
				final = append(final, layoutEntry{"zzz", entries[0].Digest})
				shared = []int{0, 1, 2, 3, 4, 5, 6, 7, 8, 9}
			case "separate":
				final = append(final, layoutEntry{
					entries[130].Slug + "!",
					entries[0].Digest,
				}, layoutEntry{
					entries[1170].Slug + "!",
					entries[0].Digest,
				})
				shared = []int{3, 4, 5, 6, 7, 11}
			}
			sort.Slice(final, func(i, j int) bool { return final[i].Slug < final[j].Slug })
			updated := checkedLayout(t, final, parent)
			requireBlocksShared(t, parent, updated, shared)
			if kind == "insert" && !reflect.DeepEqual(layoutSizes(updated)[:5], []int{128, 128, 128, 66, 65}) {
				t.Fatalf("non-global short tail was not repaired locally: %v", layoutSizes(updated))
			}
			if rewrittenEntries(parent, updated) > len(final)-len(entries)+4*128*2 {
				t.Fatal("key edit exceeded its local rewrite bound")
			}
		})
	}
}

func TestNaturalBoundaryDeletionAndEmptyWindow(t *testing.T) {
	entries := layoutKeys(320, true)
	parent := checkedLayout(t, entries, nil)
	final := append(append([]layoutEntry(nil), entries[:127]...), entries[128:]...)
	updated := checkedLayout(t, final, parent)
	requireBlocksShared(t, parent, updated, []int{0, 1, 5, 6, 7, 8, 9})
	if !reflect.DeepEqual(layoutSizes(updated)[:4], []int{32, 32, 32, 63}) {
		t.Fatalf("deleting natural boundary shifted suffix or left short tail: %v", layoutSizes(updated))
	}
	if result := checkedLayout(t, []layoutEntry{}, parent); len(result) != 0 {
		t.Fatal("deleting all members did not produce an empty root")
	}
}

func TestScatterAndRemoteGrowthKeepValueRewriteBounds(t *testing.T) {
	large := layoutKeys(37500, false)
	largeParent := checkedLayout(t, large, nil)
	small := large[:3600]
	smallParent := checkedLayout(t, small, nil)
	change := func(entries []layoutEntry, indices []int) []layoutEntry {
		final := append([]layoutEntry(nil), entries...)
		for _, index := range indices {
			digest := sha256.Sum256([]byte("updated-" + final[index].Slug))
			final[index].Digest = digest[:]
		}
		return final
	}
	local := make([]int, 125)
	scatter := make([]int, 125)
	for i := range local {
		local[i], scatter[i] = 512+i, 128*i
	}
	smallChanged := checkedLayout(t, change(small, local), smallParent)
	largeChanged := checkedLayout(t, change(large, local), largeParent)
	if rewrittenEntries(smallParent, smallChanged) != rewrittenEntries(largeParent, largeChanged) {
		t.Fatal("remote member growth increased local changed-block bytes")
	}
	scattered := checkedLayout(t, change(large, scatter), largeParent)
	if rewrittenEntries(largeParent, scattered) > 125*128 {
		t.Fatal("scattered value edits exceeded K*128")
	}
}
