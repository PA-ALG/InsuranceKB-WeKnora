package memberstore

import (
	"bytes"
	"fmt"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
)

type writeMemo struct {
	Scope     types.WikiReleaseScope
	ReleaseID string
	Raw       []types.WikiReleaseMemberSnapshot
	Rows      []contentRow
}

func snapshotBytesEqual(a, b types.WikiReleaseMemberSnapshot) bool {
	return a.Kind == b.Kind && a.LogicalSlug == b.LogicalSlug && a.RevisionID == b.RevisionID &&
		a.MemberDigest == b.MemberDigest && a.Title == b.Title && a.Content == b.Content &&
		bytes.Equal(a.Payload, b.Payload)
}

// This single-entry memo stores normalization computations, never Head/commit/membership.
// Every reuse must match the caller's exact seven raw fields AND the database parent index;
// every reused stored preimage is rehashed by PostgreSQL in the current transaction.
func (s *Store) computedContents(
	db *gorm.DB, scopeID int64, w types.WikiReleaseMemberSetWrite, parent []layoutChunk,
) ([]contentRow, []contentRow, error) {
	s.memoMu.Lock()
	memo := s.memo
	s.memoMu.Unlock()
	if memo == nil || memo.Scope != w.Scope || memo.ReleaseID != w.ParentReleaseID {
		rows, err := canonicalContents(db, scopeID, w.Members)
		return rows, rows, err
	}
	bySlug := make(map[string]int, len(memo.Raw))
	for i, m := range memo.Raw {
		bySlug[m.LogicalSlug] = i
	}
	parentRefs := make(map[string][]byte, len(memo.Raw))
	for _, c := range parent {
		for _, e := range c.Entries {
			parentRefs[e.Slug] = e.Digest
		}
	}
	all := make([]contentRow, len(w.Members))
	var novel []types.WikiReleaseMemberSnapshot
	var positions []int
	var reused [][]byte
	for i, input := range w.Members {
		j, found := bySlug[input.LogicalSlug]
		if found && snapshotBytesEqual(input, memo.Raw[j]) &&
			sameDigest(parentRefs[input.LogicalSlug], memo.Rows[j].Digest) {
			r := memo.Rows[j]
			r.ScopeID = scopeID
			all[i] = r
			reused = append(reused, r.Digest)
		} else {
			novel = append(novel, input)
			positions = append(positions, i)
		}
	}
	if err := verifyStoredPreimages(db, scopeID, reused); err != nil {
		return nil, nil, err
	}
	changed, err := canonicalContents(db, scopeID, novel)
	if err != nil {
		return nil, nil, err
	}
	for i, pos := range positions {
		all[pos] = changed[i]
	}
	return all, changed, nil
}

func (s *Store) rememberComputations(w types.WikiReleaseMemberSetWrite, rows []contentRow) {
	memo := &writeMemo{
		Scope: w.Scope, ReleaseID: w.ReleaseID, Raw: make([]types.WikiReleaseMemberSnapshot, len(w.Members)),
		Rows: append([]contentRow(nil), rows...),
	}
	for i, m := range w.Members {
		memo.Raw[i] = m
		memo.Raw[i].Payload = append([]byte(nil), m.Payload...)
		memo.Rows[i].Digest = append([]byte(nil), rows[i].Digest...)
	}
	s.memoMu.Lock()
	s.memo = memo
	s.memoMu.Unlock()
}

func verifyStoredPreimages(db *gorm.DB, scopeID int64, digests [][]byte) error {
	if len(digests) == 0 {
		return nil
	}
	packed := make([]byte, 0, len(digests)*32)
	for _, d := range digests {
		if len(d) != 32 {
			return ErrIntegrity
		}
		packed = append(packed, d...)
	}
	// int8send is network/big-endian uint64 framing for these nonnegative lengths;
	// convert_to binds exact UTF-8 bytes rather than collation/text equivalence.
	fields := []string{"kind", "logical_slug", "revision_id", "member_digest", "title", "content", "payload_json"}
	frame := fmt.Sprintf("decode('%x','hex')", []byte("enterprise-member-content.v1\x00"))
	for _, field := range fields {
		value := "convert_to(c." + field + ",'UTF8')"
		frame += "||int8send(octet_length(" + value + ")::bigint)||" + value
	}
	query := "WITH wanted AS (SELECT substring(?::bytea FROM i*32+1 FOR 32) AS " +
		"digest\n FROM generate_series(0,?::int-1) AS positions(i))\n SELECT" +
		" count(*) FROM wanted w LEFT JOIN enterprise_member_contents c\n O" +
		"N c.scope_id=? AND c.digest=w.digest WHERE c.digest IS NULL OR c." +
		"codec<>1 OR c.digest<>sha256(" + frame + `)`
	var bad int64
	if err := db.Raw(query, binaryParameter(packed), len(digests), scopeID).Scan(&bad).Error; err != nil {
		return err
	}
	if bad != 0 {
		return ErrIntegrity
	}
	return nil
}

func validSnapshotStrings(input []types.WikiReleaseMemberSnapshot) bool {
	for _, m := range input {
		if m.LogicalSlug == "" || strings.IndexByte(m.LogicalSlug, 0) >= 0 {
			return false
		}
	}
	return true
}
