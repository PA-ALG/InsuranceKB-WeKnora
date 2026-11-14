package releasestore

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// This manual capacity comparison uses the same new schema and synthetic input in
// each pair. Routine PostgreSQL CI exercises the smaller fixed-read acceptance.
func TestReleaseScaleMeasurement(t *testing.T) {
	for _, n := range []int{7300, 13000} {
		t.Run(fmt.Sprint(n), func(t *testing.T) {
			for i := 0; i < 3; i++ {
				t.Run(fmt.Sprint(i+1), func(t *testing.T) { measureFixedReads(t, n, i) })
			}
		})
	}
}

func measureFixedReads(b *testing.T, size, trial int) {
	b.Helper()
	db := openSchema(b).Session(&gorm.Session{Logger: logger.Default.LogMode(logger.Silent)})
	store := New(db, testSpaces(b))
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Minute)
	defer cancel()
	seed, updates := scaleFixture(b, size)
	start, err := store.Activate(ctx, release.ActivationWrite{
		TenantID: 7, SpaceID: "space-1", Subject: principal.Subject, CandidateID: "seed-candidate",
		BundleDigest: digestOf([]byte("seed-bundle")), DecisionID: "seed-decision",
		DecisionDigest: digestOf([]byte("seed-decision")), Nonce: "seed-nonce", Members: seed,
	})
	require.NoError(b, err)
	scope, err := testSpaces(b).Scope(7, "space-1")
	require.NoError(b, err)
	require.NoError(b, store.storage.Backfill(ctx, db, scope, start.ID, 256<<20))
	require.NoError(b, store.storage.StartObservation(ctx, db, scope))
	store = New(db, testSpaces(b))
	t0 := time.Now()
	summary, err := store.ReleaseSummary(ctx, 7, "space-1")
	require.NoError(b, err)
	t1 := time.Now()
	base, baseRows, err := store.MemberIndex(ctx, 7, "space-1", summary.ID)
	require.NoError(b, err)
	require.Len(b, baseRows, size)
	t2 := time.Now()
	slugs := make([]string, 0, len(updates))
	for _, m := range updates {
		slugs = append(slugs, m.LogicalSlug)
	}
	_, bodies, err := store.LookupMembers(ctx, 7, "space-1", base.ID, slugs)
	require.NoError(b, err)
	require.Len(b, bodies, len(updates))
	t3 := time.Now()
	svc := service(store)
	raw, err := json.Marshal(map[string]any{
		"contract_version": "1", "compiler_identity": "release-scale-test", "origin": "compile",
		"base_release_id": base.ID, "base_epoch": base.Epoch, "members": updates,
	})
	require.NoError(b, err)
	c, err := svc.Receive(ctx, principal, "space-1", raw)
	require.NoError(b, err)
	t4 := time.Now()
	d, err := svc.Decide(ctx, principal, "space-1", c.ID, approve)
	require.NoError(b, err)
	t5 := time.Now()
	receipt, err := svc.ActivateReceipt(ctx, principal, "space-1", c.ID, d.ID)
	require.NoError(b, err)
	t6 := time.Now()
	newHeader, after, err := store.MemberIndex(ctx, 7, "space-1", receipt.ID)
	require.NoError(b, err)
	require.Equal(b, receipt.ID, newHeader.ID)
	require.Len(b, after, size)
	_, sampleBodies, err := store.LookupMembers(ctx, 7, "space-1", receipt.ID, slugs)
	require.NoError(b, err)
	require.Equal(b, updates, sampleBodies)
	t7 := time.Now()
	old, err := New(db, testSpaces(b)).ReleaseByID(ctx, 7, "space-1", receipt.ID)
	require.NoError(b, err)
	require.Len(b, old.Members, size)
	t8 := time.Now()
	wireBytes := measureWire(b, summary, baseRows, bodies, receipt, newHeader, after, sampleBodies)
	if size == 13000 {
		require.LessOrEqual(b, wireBytes, release.MaxMemberReadBytes)
	}
	b.Logf("size=%d trial=%d summary=%s base_index=%s base_lookup=%s receive=%s decide=%s "+
		"activation_receipt=%s fixed_readback=%s full_read_control=%s targeted_json_bytes=%d full_json_bytes=%d",
		size, trial+1, t1.Sub(t0), t2.Sub(t1), t3.Sub(t2), t4.Sub(t3), t5.Sub(t4),
		t6.Sub(t5), t7.Sub(t6), t8.Sub(t7), wireBytes, jsonBytes(b, old))
}

func scaleFixture(b *testing.T, n int) ([]release.Member, []release.Member) {
	b.Helper()
	seed := make([]release.Member, 0, n)
	updates := make([]release.Member, 0, 125)
	for i := range n {
		product, slug := fmt.Sprintf("product-%03d", i/125), fmt.Sprintf("claim-%05d", i)
		payload, err := json.Marshal(map[string]string{
			"subject_ref": product, "logical_key": slug,
			"value": strings.Repeat(string(rune('a'+i%26)), 2200+(i%4)*1200),
		})
		require.NoError(b, err)
		digest, err := release.MemberDigest(payload)
		require.NoError(b, err)
		seed = append(seed, release.Member{
			Kind: "claim", LogicalSlug: slug, Payload: payload,
			MemberDigest: digest, AccessScope: "space",
		})
		if i < 125 {
			var changed map[string]string
			require.NoError(b, json.Unmarshal(payload, &changed))
			changed["value"] += " updated"
			data, err := json.Marshal(changed)
			require.NoError(b, err)
			digest, err := release.MemberDigest(data)
			require.NoError(b, err)
			updates = append(updates, release.Member{
				Kind: "claim", LogicalSlug: slug, Payload: data,
				MemberDigest: digest, AccessScope: "space",
			})
		}
	}
	return seed, updates
}

func jsonBytes(b *testing.T, data any) int {
	b.Helper()
	raw, err := json.Marshal(map[string]any{"success": true, "data": data})
	require.NoError(b, err)
	return len(raw)
}

func measureWire(t *testing.T, base release.Release, before, bases []release.Member,
	receipt release.ActivationReceipt, after release.Release, index, bodies []release.Member,
) int {
	t.Helper()
	head := func(r release.Release) map[string]any {
		return map[string]any{
			"id": r.ID, "epoch": r.Epoch, "base_release_id": r.BaseReleaseID,
			"candidate_id": r.CandidateID, "decision_digest": r.DecisionDigest,
		}
	}
	project := func(rows []release.Member) []map[string]any {
		out := make([]map[string]any, 0, len(rows))
		for _, row := range rows {
			var r map[string]any
			require.NoError(t, json.Unmarshal(row.Payload, &r))
			r["kind"], r["logical_slug"], r["member_digest"] = row.Kind, row.LogicalSlug, row.MemberDigest
			out = append(out, r)
		}
		return out
	}
	bh, ah := head(base), head(after)
	total := jsonBytes(t, bh) + jsonBytes(t, receipt)
	bh["members"], ah["members"] = project(before), project(index)
	total += jsonBytes(t, bh) + jsonBytes(t, ah)
	bh["members"], ah["members"] = bases, bodies
	bh["missing"], ah["missing"] = []string{}, []string{}
	return total + jsonBytes(t, bh) + jsonBytes(t, ah)
}
