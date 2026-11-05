package memberstore

import (
	"encoding/json"
	"fmt"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"unsafe"

	"github.com/Tencent/WeKnora/internal/types"
)

func memoMemoryScope() types.WikiReleaseScope {
	return types.WikiReleaseScope{TenantID: 1, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki"}
}

// memoStringReferences inspects the actual object graph rather than just the
// inline size of a memo. A small header can still retain a large backing array.
func memoStringReferences(v reflect.Value, visit func(string, uintptr)) {
	switch v.Kind() {
	case reflect.Pointer:
		if !v.IsNil() {
			memoStringReferences(v.Elem(), visit)
		}
	case reflect.Struct:
		for i := 0; i < v.NumField(); i++ {
			memoStringReferences(v.Field(i), visit)
		}
	case reflect.Slice:
		if v.Type().Elem().Kind() == reflect.Uint8 {
			if v.Len() != 0 {
				visit(string(v.Bytes()), v.Pointer())
			}
			return
		}
		for i := 0; i < v.Len(); i++ {
			memoStringReferences(v.Index(i), visit)
		}
	case reflect.String:
		s := v.String()
		visit(s, uintptr(unsafe.Pointer(unsafe.StringData(s))))
	}
}

func TestComputationMemoDoesNotRetainSnapshotBodiesOrInputBacking(t *testing.T) {
	backing := "m/000001" + strings.Repeat("unused slug backing", 4096)
	input := types.WikiReleaseMemberSnapshot{
		Kind: "page", LogicalSlug: backing[:8], RevisionID: "revision",
		MemberDigest: strings.Repeat("a", 64), Title: "distinct title",
		Content: "retained content sentinel:" + strings.Repeat("x", 4096),
		Payload: json.RawMessage(`{"raw":"` + strings.Repeat("y", 4096) + `"}`),
	}
	store := New()
	w := types.WikiReleaseMemberSetWrite{
		Scope: memoMemoryScope(), ReleaseID: "remembered", Members: []types.WikiReleaseMemberSnapshot{input},
	}
	store.rememberComputations(w, []contentRow{encodeContent(1, input)})
	start := uintptr(unsafe.Pointer(unsafe.StringData(backing)))
	end := start + uintptr(len(backing))
	var bodies, aliases int
	memoStringReferences(reflect.ValueOf(store.memo), func(value string, pointer uintptr) {
		if value == input.Content || value == string(input.Payload) || value == input.Title {
			bodies++
		}
		if pointer >= start && pointer < end {
			aliases++
		}
	})
	if bodies != 0 || aliases != 0 {
		t.Fatalf("memo retained %d snapshot body fields and %d references into input slug backing; keep hashes and an owned slug only", bodies, aliases)
	}
	runtime.KeepAlive(backing)
	runtime.KeepAlive(input)
}

//go:noinline
func retainedMemoFixture(count, width int) *Store {
	input := make([]types.WikiReleaseMemberSnapshot, count)
	rows := make([]contentRow, count)
	for i := range input {
		input[i] = types.WikiReleaseMemberSnapshot{
			Kind: "page", LogicalSlug: fmt.Sprintf("m/%06d", i), RevisionID: "revision",
			MemberDigest: strings.Repeat("a", 64), Title: fmt.Sprintf("title/%06d", i),
			Content: fmt.Sprintf("%08d", i) + strings.Repeat("c", width),
			Payload: json.RawMessage(fmt.Sprintf(`{"i":%d,"raw":"%s"}`, i, strings.Repeat("p", width))),
		}
		rows[i] = encodeContent(1, input[i])
	}
	store := New()
	store.rememberComputations(types.WikiReleaseMemberSetWrite{
		Scope: memoMemoryScope(), ReleaseID: "remembered", Members: input,
	}, rows)
	return store
}

func TestComputationMemoRetainedHeap37500(t *testing.T) {
	const count = 37500
	// Warm up fmt/runtime pools before measuring. The fixture returns only the
	// Store, so caller snapshots and rows become unreachable before the second GC.
	warm := retainedMemoFixture(1, 1024)
	runtime.KeepAlive(warm)
	runtime.GC()
	var before, after runtime.MemStats
	runtime.ReadMemStats(&before)
	store := retainedMemoFixture(count, 1024)
	runtime.GC()
	runtime.ReadMemStats(&after)
	retained := int64(after.HeapAlloc) - int64(before.HeapAlloc)
	const limit = count*100 + 64*1024
	t.Logf("members=%d width=%d retained_heap_bytes=%d bytes_per_member=%.2f limit_bytes=%d", count, 1024, retained, float64(retained)/count, limit)
	if retained > limit {
		t.Errorf("memo retains %d bytes (%.2f B/member); budget is %d bytes, independent of content/payload width", retained, float64(retained)/count, limit)
	}
	runtime.KeepAlive(store)
}

func BenchmarkComputationMemoRemember37500(b *testing.B) {
	input := make([]types.WikiReleaseMemberSnapshot, 37500)
	rows := make([]contentRow, len(input))
	for i := range input {
		input[i] = types.WikiReleaseMemberSnapshot{
			Kind: "page", LogicalSlug: fmt.Sprintf("m/%06d", i),
			Content: strings.Repeat("c", 1024), Payload: json.RawMessage(`{"n":9007199254740993}`),
		}
		rows[i] = encodeContent(1, input[i])
	}
	w := types.WikiReleaseMemberSetWrite{Scope: memoMemoryScope(), ReleaseID: "remembered", Members: input}
	store := New()
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		store.rememberComputations(w, rows)
	}
	runtime.KeepAlive(store)
}
