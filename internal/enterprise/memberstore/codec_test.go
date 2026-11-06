package memberstore

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"reflect"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
)

func TestContentCodecFrozenIdentity(t *testing.T) {
	snapshot := types.WikiReleaseMemberSnapshot{
		Kind: "entity", LogicalSlug: "s/é", RevisionID: "r\x00v", MemberDigest: "md",
		Title: "Title", Content: "line\ntext", Payload: json.RawMessage(`{"n": 9007199254740993, "s": "é"}`),
	}
	row := encodeContent(17, snapshot)
	if hex.EncodeToString(row.Digest) != "e4b72064251bc7792c8e732f0d6519a0599fd579e752611206ec3aa8edcec645" {
		t.Fatalf("content codec identity differs: %x", row.Digest)
	}
	if row.ScopeID != 17 || row.Codec != 1 || !validContent(row) || !reflect.DeepEqual(contentSnapshot(row), snapshot) {
		t.Fatalf("content round trip lost the complete snapshot: %#v", row)
	}
	if other := encodeContent(18, snapshot); !bytes.Equal(other.Digest, row.Digest) || other.ScopeID == row.ScopeID {
		t.Fatal("scope belongs in composite keys, not the content codec")
	}
	mutations := []func(*contentRow){
		func(c *contentRow) { c.Kind += "x" }, func(c *contentRow) { c.LogicalSlug += "x" },
		func(c *contentRow) { c.RevisionID += "x" }, func(c *contentRow) { c.MemberDigest += "x" },
		func(c *contentRow) { c.Title += "x" }, func(c *contentRow) { c.Content += "x" },
		func(c *contentRow) { c.PayloadJSON = `{"n": 9007199254740992, "s": "é"}` },
		func(c *contentRow) { c.Codec = 2 }, func(c *contentRow) { c.Digest = c.Digest[:31] },
		func(c *contentRow) { c.Digest = bytes.Repeat([]byte{7}, 32) },
	}
	for i, mutate := range mutations {
		changed := row
		mutate(&changed)
		if validContent(changed) {
			t.Fatalf("mutation %d was accepted under the old identity", i)
		}
	}
	detached := contentSnapshot(row)
	detached.Payload[0] = '['
	if row.PayloadJSON != string(snapshot.Payload) {
		t.Fatal("snapshot payload aliases stored bytes")
	}
}

func TestContentCodecDoesNotNormalizeStringsOrJSON(t *testing.T) {
	base := types.WikiReleaseMemberSnapshot{
		Kind: "", LogicalSlug: "a",
		Content: "é\n", Payload: json.RawMessage(`{"x": 9007199254740993}`),
	}
	for _, change := range []func(*types.WikiReleaseMemberSnapshot){
		func(s *types.WikiReleaseMemberSnapshot) { s.Kind = "page" },
		func(s *types.WikiReleaseMemberSnapshot) { s.Content = "é\n" },
		func(s *types.WikiReleaseMemberSnapshot) { s.Content = "é\r\n" },
		func(s *types.WikiReleaseMemberSnapshot) { s.Payload = json.RawMessage(`{"x":9007199254740993}`) },
		func(s *types.WikiReleaseMemberSnapshot) { s.Payload = json.RawMessage(`{"x": 9007199254740992}`) },
	} {
		other := base
		change(&other)
		if bytes.Equal(encodeContent(1, base).Digest, encodeContent(1, other).Digest) {
			t.Fatalf("distinct exact snapshot bytes merged: %#v", other)
		}
	}
	left := types.WikiReleaseMemberSnapshot{Kind: "a", LogicalSlug: "bc"}
	right := types.WikiReleaseMemberSnapshot{Kind: "ab", LogicalSlug: "c"}
	if bytes.Equal(encodeContent(1, left).Digest, encodeContent(1, right).Digest) {
		t.Fatal("length-prefixed fields became ambiguous")
	}
}

func TestChunkAndSetCodecFrozenIdentity(t *testing.T) {
	entries := []layoutEntry{{Slug: "a", Digest: make([]byte, 32)}, {Slug: "é", Digest: bytes.Repeat([]byte{255}, 32)}}
	chunk := encodeChunk(11, entries)
	if chunk.ScopeID != 11 || chunk.Codec != 1 || chunk.Count != 2 || len(chunk.Refs) != 64 {
		t.Fatalf("bad compact chunk: %#v", chunk)
	}
	if hex.EncodeToString(chunk.Digest) != "ed55dd5c5b904c986f2c9d775937cc527b315695d4d7d5b08485788d469f93a5" ||
		!bytes.Equal(chunk.Refs, append(make([]byte, 32), bytes.Repeat([]byte{255}, 32)...)) {
		t.Fatalf("chunk codec differs: %x", chunk.Digest)
	}
	chunks := []chunkRow{{Count: 2, Digest: bytes.Repeat([]byte{17},
		32)}, {Count: 1, Digest: bytes.Repeat([]byte{34}, 32)}}
	set := encodeSet(11, "slug_asc", chunks)
	if set.ScopeID != 11 || set.Codec != 1 || set.OrderMode != "slug_asc" ||
		set.MemberCount != 3 || set.ChunkCount != 2 || len(set.Blocks) != 72 {
		t.Fatalf("bad compact set: %#v", set)
	}
	if hex.EncodeToString(set.Digest) != "82d14c5adbd80eca38291694b527251f5b9b6a555d4d0668209114c0172c305f" ||
		binary.BigEndian.Uint32(set.Blocks[:4]) != 2 || binary.BigEndian.Uint32(set.Blocks[36:40]) != 1 {
		t.Fatalf("root codec differs: %x", set.Digest)
	}
	if bytes.Equal(set.Digest, encodeSet(11, "legacy_sequence", chunks).
		Digest) || bytes.Equal(set.Digest, encodeSet(11, "slug_asc", []chunkRow{chunks[1], chunks[0]}).
		Digest) {
		t.Fatal("root identity does not bind order mode and ordered blocks")
	}
	empty := encodeSet(11, "slug_asc", nil)
	if empty.MemberCount != 0 || empty.ChunkCount != 0 || len(empty.Blocks) != 0 || len(empty.Digest) != 32 {
		t.Fatalf("invalid empty root: %#v", empty)
	}
	entries[0].Digest[0] = 3
	if chunk.Refs[0] != 0 {
		t.Fatal("encoded refs alias input digests")
	}
}
