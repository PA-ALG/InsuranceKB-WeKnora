package memberstore

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
)

// MemberSelection contains projected or full rows and the verified layout's pairs.
type MemberSelection struct {
	Pairs   []types.WikiReleaseMemberSnapshot
	Members []types.WikiReleaseMemberSnapshot
}

// Select reads a narrow ownership index or just the requested full members. The
// accompanying pairs let the caller validate completeness against its manifest.
// A nil slug list selects the index projection, never a full read.
func (s *Store) Select(ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope,
	id string, limit int, slugs []string,
) (out MemberSelection, err error) {
	err = s.ValidateRead(ctx, db, scope, id, func(ctx context.Context) error {
		header := ctx.Value(readSelectionKey{}).(readSelection).header
		tx := db.WithContext(ctx)
		if header.MemberStorage == "chunks.v1" {
			out, err = chunkSelection(tx, scope, id, limit, slugs)
		} else {
			out, err = legacySelection(tx, id, limit, slugs)
		}
		return err
	})
	if err != nil {
		return MemberSelection{}, err
	}
	return out, nil
}

// ErrReadLimit is a bounded-read refusal. The enclosing producer maps it to the
// public error without recording an integrity failure of a healthy Release.
var ErrReadLimit = errors.New("member selection is too large")

func legacySelection(db *gorm.DB, id string, limit int, slugs []string) (MemberSelection, error) {
	query := db.Model(&types.WikiReleaseMember{}).Where("release_id = ?", id).Order("logical_slug ASC")
	if slugs != nil {
		if err := boundLegacyBodies(db, id, slugs); err != nil {
			return MemberSelection{}, err
		}
		var rows []types.WikiReleaseMember
		if err := query.Where("logical_slug IN ?", slugs).Find(&rows).Error; err != nil {
			return MemberSelection{}, err
		}
		out := MemberSelection{Members: make([]types.WikiReleaseMemberSnapshot, 0, len(rows))}
		for _, row := range rows {
			out.Members = append(out.Members, row.Snapshot())
		}
		return out, nil
	}
	const envelope = "(content::jsonb->>'payload')::jsonb"
	return readProjection(query.Select(projectionColumns(envelope)+`,
 (content::jsonb->'v'='1'::jsonb AND (content::jsonb->>'payload')::jsonb = payload) AS valid`).
		Limit(limit+1), limit)
}

func chunkSelection(db *gorm.DB, scope types.WikiReleaseScope, id string, limit int,
	slugs []string,
) (MemberSelection, error) {
	root, err := releaseRoot(db, scope, id)
	if err != nil {
		return MemberSelection{}, failedRead(err)
	}
	if root.OrderMode != "slug_asc" || root.MemberCount < 0 {
		return MemberSelection{}, ErrIntegrity
	}
	if root.MemberCount > int64(limit) {
		return MemberSelection{}, ErrReadLimit
	}
	layout, pairs, err := readLayout(db, root, false)
	if err != nil {
		return MemberSelection{}, err
	}
	var keys [][]byte
	wanted := make(map[string]bool, len(slugs))
	for _, slug := range slugs {
		wanted[slug] = true
	}
	for _, chunk := range layout {
		for _, entry := range chunk.Entries {
			if slugs == nil || wanted[entry.Slug] {
				keys = append(keys, entry.Digest)
			}
		}
	}
	query := byDigests(db, "enterprise_member_contents", root.ScopeID, keys)
	if slugs == nil {
		// Verify the authenticated ownership preimage in SQL without transferring
		// the bodies. A corrupted subject must not silently hide a historical Claim.
		if err := verifyStoredPreimages(db, root.ScopeID, keys); err != nil {
			return MemberSelection{}, err
		}
		projected, err := readProjection(query.Order("c.logical_slug ASC").
			Select(projectionColumns("c.payload_json::jsonb")+", true AS valid"), limit)
		projected.Pairs = pairs
		return projected, err
	}
	var objects []contentRow
	if len(keys) > 0 {
		var size int64
		if err := query.Session(&gorm.Session{}).
			Select("COALESCE(sum(octet_length(c.content)+octet_length(c.payload_json)),0)").
			Scan(&size).Error; err != nil {
			return MemberSelection{}, err
		}
		if size > maxSelectionStorageBytes {
			return MemberSelection{}, ErrReadLimit
		}
		if err := query.Order("c.logical_slug ASC").Find(&objects).Error; err != nil {
			return MemberSelection{}, err
		}
	}
	if len(objects) != len(keys) {
		return MemberSelection{}, ErrIntegrity
	}
	out := MemberSelection{Pairs: pairs, Members: make([]types.WikiReleaseMemberSnapshot, 0, len(objects))}
	for _, row := range objects {
		if !wanted[row.LogicalSlug] || !validContent(row) {
			return MemberSelection{}, ErrIntegrity
		}
		out.Members = append(out.Members, contentSnapshot(row))
	}
	return out, nil
}

// A projection selects only claim ownership and entity identity. jsonb_typeof
// preserves the old reader's distinction between a string and other JSON types.
func projectionColumns(payload string) string {
	return `kind, logical_slug, member_digest,
 CASE WHEN kind='claim' THEN jsonb_strip_nulls(jsonb_build_object(
 'logical_key', CASE WHEN jsonb_typeof((` + payload + `)->'logical_key')='string'
 THEN (` + payload + `)->'logical_key' END,
 'subject_ref', CASE WHEN jsonb_typeof((` + payload + `)->'subject_ref')='string'
 THEN (` + payload + `)->'subject_ref' END))
 WHEN kind='entity' THEN jsonb_strip_nulls(jsonb_build_object(
 'entity_id', CASE WHEN jsonb_typeof((` + payload + `)->'entity_id')='string' THEN (` + payload + `)->'entity_id' END))
 ELSE '{}'::jsonb END AS projection`
}

func readProjection(db *gorm.DB, limit int) (MemberSelection, error) {
	var rows []struct {
		Kind, LogicalSlug, MemberDigest, Projection string
		Valid                                       bool
	}
	if err := db.Scan(&rows).Error; err != nil {
		return MemberSelection{}, err
	}
	if len(rows) > limit {
		return MemberSelection{}, ErrReadLimit
	}
	out := MemberSelection{Members: make([]types.WikiReleaseMemberSnapshot, 0, len(rows))}
	for _, row := range rows {
		if !row.Valid {
			return MemberSelection{}, ErrIntegrity
		}
		out.Members = append(out.Members, types.WikiReleaseMemberSnapshot{
			Kind: row.Kind, LogicalSlug: row.LogicalSlug, MemberDigest: row.MemberDigest,
			Payload: json.RawMessage(row.Projection),
		})
	}
	return out, nil
}

// The database stores an envelope and a second copy of the payload. Bound both
// before loading selected bodies, then enforce the exact wire budget at the router.
const maxSelectionStorageBytes = 32 << 20

func boundLegacyBodies(db *gorm.DB, id string, slugs []string) error {
	var size int64
	if err := db.Model(&types.WikiReleaseMember{}).Where("release_id = ? AND logical_slug IN ?", id, slugs).
		Select("COALESCE(sum(octet_length(content)+octet_length(payload::text)),0)").Scan(&size).Error; err != nil {
		return err
	}
	if size > maxSelectionStorageBytes {
		return ErrReadLimit
	}
	return nil
}
