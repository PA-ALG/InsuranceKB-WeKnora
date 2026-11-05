package memberstore

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"

	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
)

func releaseRoot(db *gorm.DB, scope types.WikiReleaseScope, id string) (setRow, error) {
	var r setRow
	err := db.Table("enterprise_member_sets AS roots").Select("roots.*").
		Joins(`JOIN enterprise_member_releases AS owners
 ON owners.scope_id=roots.scope_id AND owners.root_digest=roots.digest`).
		Joins("JOIN enterprise_member_scopes AS scopes ON scopes.id=owners.scope_id").
		Where("owners.release_id = ? AND owners.verified", id).
		Where("owners.tenant_id=? AND owners.space_id=? AND owners.raw_kb_id=? A"+
			"ND owners.wiki_kb_id=?",
			scope.TenantID, scope.SpaceID, scope.RawKBID, scope.WikiKBID,
		).
		Where("scopes.tenant_id=? AND scopes.space_id=? AND scopes.raw_kb_id=? A"+
			"ND scopes.wiki_kb_id=?",
			scope.TenantID, scope.SpaceID, scope.RawKBID, scope.WikiKBID,
		).
		Take(&r).Error
	return r, err
}

// readLayout validates the immutable internal layout. Release-facing output optionally
// uses the legacy column collation; preparation arrays retain their internal sequence.
func readLayout(
	db *gorm.DB, root setRow, full bool, releaseOrder ...bool,
) ([]layoutChunk, []types.WikiReleaseMemberSnapshot, error) {
	if root.Codec != 1 || root.MemberCount < 0 || root.ChunkCount < 0 || len(root.Digest) != 32 ||
		root.OrderMode != "slug_asc" && root.OrderMode != "legacy_sequence" ||
		int64(root.ChunkCount)*36 != int64(len(root.Blocks)) {
		return nil, nil, ErrIntegrity
	}
	blockKeys := make([][]byte, root.ChunkCount)
	counts := make([]int, root.ChunkCount)
	var total int64
	for i := range blockKeys {
		off := i * 36
		counts[i] = int(binary.BigEndian.Uint32(root.Blocks[off : off+4]))
		blockKeys[i] = root.Blocks[off+4 : off+36]
		if counts[i] < 1 || counts[i] > 128 || i+1 < len(blockKeys) && counts[i] < 32 {
			return nil, nil, ErrIntegrity
		}
		total += int64(counts[i])
	}
	if total != root.MemberCount {
		return nil, nil, ErrIntegrity
	}
	var storedChunks []chunkRow
	if len(blockKeys) > 0 {
		if err := byDigests(db, "enterprise_member_chunks", root.ScopeID, blockKeys).
			Find(&storedChunks).Error; err != nil {
			return nil, nil, err
		}
	}
	chunksByKey := make(map[string]chunkRow, len(storedChunks))
	for _, c := range storedChunks {
		chunksByKey[string(c.Digest)] = c
	}
	ordered := make([]chunkRow, len(blockKeys))
	objectKeys := make([][]byte, 0, total)
	for i, key := range blockKeys {
		c, ok := chunksByKey[string(key)]
		if !ok || c.ScopeID != root.ScopeID || c.Codec != 1 || c.Count != counts[i] ||
			int64(c.Count)*32 != int64(len(c.Refs)) {
			return nil, nil, ErrIntegrity
		}
		ordered[i] = c
		for j := 0; j < c.Count; j++ {
			objectKeys = append(objectKeys, c.Refs[j*32:j*32+32])
		}
	}
	rebuilt := encodeSet(root.ScopeID, root.OrderMode, ordered)
	if !sameDigest(root.Digest, rebuilt.Digest) || !bytes.Equal(root.Blocks, rebuilt.Blocks) {
		return nil, nil, ErrIntegrity
	}
	var objects []contentRow
	query := byDigests(db, "enterprise_member_contents", root.ScopeID, objectKeys)
	if len(releaseOrder) > 0 && releaseOrder[0] {
		query = query.Order("c.logical_slug ASC")
	}
	if !full {
		query = query.Select("c.scope_id", "c.digest", "c.codec", "c.logical_slug", "c.member_digest")
	}
	if len(objectKeys) > 0 {
		if err := query.Find(&objects).Error; err != nil {
			return nil, nil, err
		}
	}
	byKey := make(map[string]contentRow, len(objects))
	for _, r := range objects {
		byKey[string(r.Digest)] = r
	}
	layout := make([]layoutChunk, len(ordered))
	snapshots := make([]types.WikiReleaseMemberSnapshot, 0, total)
	seen := make(map[string]bool, len(objects))
	previous := ""
	for i, c := range ordered {
		entries := make([]layoutEntry, c.Count)
		for j := range entries {
			key := c.Refs[j*32 : j*32+32]
			r, ok := byKey[string(key)]
			if !ok || r.ScopeID != root.ScopeID || r.Codec != 1 || len(r.Digest) != 32 ||
				r.LogicalSlug == "" || seen[r.LogicalSlug] {
				return nil, nil, ErrIntegrity
			}
			if root.OrderMode == "slug_asc" && len(seen) > 0 && r.LogicalSlug <= previous {
				return nil, nil, ErrIntegrity
			}
			if full && !validContent(r) {
				return nil, nil, ErrIntegrity
			}
			seen[r.LogicalSlug] = true
			previous = r.LogicalSlug
			entries[j] = layoutEntry{r.LogicalSlug, r.Digest}
			snapshots = append(snapshots, contentSnapshot(r))
		}
		if !sameDigest(encodeChunk(root.ScopeID, entries).Digest, c.Digest) {
			return nil, nil, ErrIntegrity
		}
		layout[i] = layoutChunk{entries}
	}
	if int64(len(snapshots)) != root.MemberCount {
		return nil, nil, ErrIntegrity
	}
	if len(releaseOrder) > 0 && releaseOrder[0] {
		snapshots = snapshots[:0]
		for _, object := range objects {
			snapshots = append(snapshots, contentSnapshot(object))
		}
	}
	return layout, snapshots, nil
}

// Read preserves explicitly legacy/bridge reads; chunks.v1 never falls back to a retained copy.
func (s *Store) readValidated(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, id string,
) (out []types.WikiReleaseMemberSnapshot, failure error) {
	tx := db.WithContext(ctx)
	header, err := releaseHeader(tx, scope, id)
	if err != nil {
		return nil, err
	}
	switch header.MemberStorage {
	case "", "bridge.v1":
		return legacyMembers(tx, id)
	case "chunks.v1":
		root, err := releaseRoot(tx, scope, id)
		if err != nil {
			return nil, failedRead(err)
		}
		if root.OrderMode != "slug_asc" {
			return nil, ErrIntegrity
		}
		_, snapshots, err := readLayout(tx, root, true, true)
		return snapshots, err
	default:
		return nil, ErrIntegrity
	}
}

// Digests verifies the entire ordered index without fetching payload/content columns.
func (s *Store) digestsValidated(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, id string, header types.WikiRelease,
) (out map[string]string, failure error) {
	tx := db.WithContext(ctx)
	var rows []types.WikiReleaseMemberSnapshot
	switch header.MemberStorage {
	case "", "bridge.v1":
		var pairs []struct{ LogicalSlug, MemberDigest string }
		if err := tx.Model(&types.WikiReleaseMember{}).Select("logical_slug", "member_digest").
			Where("release_id = ?", id).Order("logical_slug ASC").Scan(&pairs).
			Error; err != nil {
			return nil, err
		}
		rows = make([]types.WikiReleaseMemberSnapshot, len(pairs))
		for i, p := range pairs {
			rows[i] = types.WikiReleaseMemberSnapshot{LogicalSlug: p.LogicalSlug, MemberDigest: p.MemberDigest}
		}
	case "chunks.v1":
		root, err := releaseRoot(tx, scope, id)
		if err != nil {
			return nil, failedRead(err)
		}
		if root.OrderMode != "slug_asc" {
			return nil, ErrIntegrity
		}
		_, rows, err = readLayout(tx, root, false)
		if err != nil {
			return nil, err
		}
	default:
		return nil, ErrIntegrity
	}
	out = make(map[string]string, len(rows))
	for _, r := range rows {
		out[r.LogicalSlug] = r.MemberDigest
	}
	return out, nil
}

func preparationRoot(db *gorm.DB, scope types.WikiReleaseScope, id string) (setRow, error) {
	var r setRow
	err := db.Table("enterprise_member_sets AS roots").Select("roots.*").
		Joins(`JOIN enterprise_member_preparations AS owners
 ON owners.scope_id=roots.scope_id AND owners.root_digest=roots.digest`).
		Joins("JOIN enterprise_member_scopes AS scopes ON scopes.id=owners.scope_id").
		Where("owners.preparation_id = ? AND owners.verified", id).
		Where("owners.tenant_id=? AND owners.space_id=? AND owners.raw_kb_id=? A"+
			"ND owners.wiki_kb_id=?",
			scope.TenantID, scope.SpaceID, scope.RawKBID, scope.WikiKBID,
		).
		Where("scopes.tenant_id=? AND scopes.space_id=? AND scopes.raw_kb_id=? A"+
			"ND scopes.wiki_kb_id=?",
			scope.TenantID, scope.SpaceID, scope.RawKBID, scope.WikiKBID,
		).
		Take(&r).Error
	return r, err
}

func preparationMembers(
	db *gorm.DB, scope types.WikiReleaseScope, id string,
) ([]types.WikiReleaseMemberSnapshot, error) {
	var row struct{ Members json.RawMessage }
	if err := exactScope(db.Table("wiki_release_preparations"), scope).
		Where("preparation_id = ?", id).Select("members").Take(&row).Error; err != nil {
		return nil, err
	}
	var out []types.WikiReleaseMemberSnapshot
	if err := json.Unmarshal(row.Members, &out); err != nil {
		return nil, ErrIntegrity
	}
	return out, nil
}
