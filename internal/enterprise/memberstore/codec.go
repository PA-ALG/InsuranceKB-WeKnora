package memberstore

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"hash"

	"github.com/Tencent/WeKnora/internal/types"
)

func encodeContent(scopeID int64, snapshot types.WikiReleaseMemberSnapshot) contentRow {
	row := contentRow{
		ScopeID: scopeID, Codec: 1, Kind: snapshot.Kind, LogicalSlug: snapshot.LogicalSlug,
		RevisionID: snapshot.RevisionID, MemberDigest: snapshot.MemberDigest,
		Title: snapshot.Title, Content: snapshot.Content, PayloadJSON: string(snapshot.Payload),
	}
	row.Digest = contentStorageDigest(row)
	return row
}

func contentSnapshot(row contentRow) types.WikiReleaseMemberSnapshot {
	return types.WikiReleaseMemberSnapshot{
		Kind: row.Kind, LogicalSlug: row.LogicalSlug, RevisionID: row.RevisionID,
		MemberDigest: row.MemberDigest, Title: row.Title, Content: row.Content,
		Payload: json.RawMessage(row.PayloadJSON),
	}
}

func validContent(row contentRow) bool {
	return row.Codec == 1 && len(row.Digest) == sha256.Size && bytes.Equal(row.Digest, contentStorageDigest(row))
}

func contentStorageDigest(row contentRow) []byte {
	digest := sha256.New()
	digest.Write([]byte("enterprise-member-content.v1\x00"))
	for _, field := range []string{
		row.Kind, row.LogicalSlug, row.RevisionID, row.MemberDigest, row.Title, row.Content, row.PayloadJSON,
	} {
		writeCodecString(digest, field)
	}
	return digest.Sum(nil)
}

func encodeChunk(scopeID int64, entries []layoutEntry) chunkRow {
	row := chunkRow{ScopeID: scopeID, Codec: 1, Count: len(entries), Refs: make([]byte, 0, len(entries)*sha256.Size)}
	digest := sha256.New()
	digest.Write([]byte("enterprise-member-chunk.v1\x00"))
	var count [4]byte
	binary.BigEndian.PutUint32(count[:], uint32(row.Count))
	digest.Write(count[:])
	for _, entry := range entries {
		writeCodecString(digest, entry.Slug)
		digest.Write(entry.Digest)
		row.Refs = append(row.Refs, entry.Digest...)
	}
	row.Digest = digest.Sum(nil)
	return row
}

func encodeSet(scopeID int64, mode string, chunks []chunkRow) setRow {
	row := setRow{
		ScopeID: scopeID, Codec: 1, OrderMode: mode, ChunkCount: len(chunks), Blocks: make([]byte, 0, len(chunks)*36),
	}
	for _, chunk := range chunks {
		row.MemberCount += int64(chunk.Count)
		var count [4]byte
		binary.BigEndian.PutUint32(count[:], uint32(chunk.Count))
		row.Blocks = append(row.Blocks, count[:]...)
		row.Blocks = append(row.Blocks, chunk.Digest...)
	}
	digest := sha256.New()
	digest.Write([]byte("enterprise-member-chunk-set.v1\x00"))
	writeCodecString(digest, mode)
	var counts [12]byte
	binary.BigEndian.PutUint64(counts[:8], uint64(row.MemberCount))
	binary.BigEndian.PutUint32(counts[8:], uint32(row.ChunkCount))
	digest.Write(counts[:])
	digest.Write(row.Blocks)
	row.Digest = digest.Sum(nil)
	return row
}

// Inputs have already passed boundary validation. Hash writes cannot fail.
func writeCodecString(digest hash.Hash, value string) {
	var length [8]byte
	binary.BigEndian.PutUint64(length[:], uint64(len(value)))
	digest.Write(length[:])
	digest.Write([]byte(value))
}
