package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"
	"time"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

type entityPageGraphReleaseSource830G1Spy struct {
	current       EntityPageGraphReleaseSnapshot830G1
	pinned        EntityPageGraphReleaseSnapshot830G1
	currentErr    error
	pinnedErr     error
	currentCalls  int
	pinnedCalls   int
	pinnedRelease []string
}

func (s *entityPageGraphReleaseSource830G1Spy) LoadCurrentEntityPageGraphRelease830G1(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	s.currentCalls++
	return s.current, s.currentErr
}

func (s *entityPageGraphReleaseSource830G1Spy) LoadPinnedEntityPageGraphRelease830G1(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	releaseID string,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	s.pinnedCalls++
	s.pinnedRelease = append(s.pinnedRelease, releaseID)
	return s.pinned, s.pinnedErr
}

func entityPageGraphReleaseFixture830G1(t *testing.T) EntityPageGraphReleaseSnapshot830G1 {
	t.Helper()
	raw := loadEntityPageGraph830G1ServiceVector(t)
	manifest, err := types.ParseEntityPageManifest830G1(raw)
	require.NoError(t, err)
	members := make([]types.WikiReleaseMemberSnapshot, 0, len(manifest.Members))
	for _, member := range manifest.Members {
		members = append(members, types.WikiReleaseMemberSnapshot{
			Kind: member.PageKind, LogicalSlug: member.PageID,
			RevisionID: member.PayloadSHA256, MemberDigest: member.MemberDigest,
			Title: member.ShortTitle, Content: "", Payload: append(json.RawMessage(nil), member.Payload...),
		})
	}
	return EntityPageGraphReleaseSnapshot830G1{
		ReleaseID: manifest.ReleaseID, ActivationEpoch: manifest.ActivationEpoch,
		Manifest: append(json.RawMessage(nil), raw...), Members: members,
	}
}

func loadEntityPageGraph830G1ServiceVector(t *testing.T) []byte {
	t.Helper()
	return readServiceTestFile(t, "../../../harness/tests/fixtures/entity_page_graph_830_g1_contract_vector.json")
}

func TestEntityPageGraphService830G1CurrentPinsOnceAndPinnedNeverFallsBack(t *testing.T) {
	t.Parallel()
	snapshot := entityPageGraphReleaseFixture830G1(t)
	selector := EntityPageGraphSelector830G1{
		EntityID: "ping-an-e-sheng-bao", PageKind: "field", StableKey: "cooling_off_period",
	}
	principal := types.WikiReleasePrincipal{ID: "viewer", TenantID: 7, SpaceID: snapshotManifestSpace(t, snapshot)}
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: principal.SpaceID, RawKBID: "raw-596-1", WikiKBID: "8d5695de-f255-42d5-9a41-042ba86e97b9",
	}

	t.Run("current observes the head-backed source once", func(t *testing.T) {
		spy := &entityPageGraphReleaseSource830G1Spy{current: snapshot}
		result, err := NewEntityPageGraphService830G1(spy).ReadCurrentEntityPage830G1(
			context.Background(), principal, scope, selector,
		)
		require.NoError(t, err)
		require.Equal(t, "current", result.ReadMode)
		require.Equal(t, snapshot.ReleaseID, result.ReleaseID)
		require.Equal(t, 1, spy.currentCalls)
		require.Zero(t, spy.pinnedCalls)
	})

	t.Run("explicit pinned reads only the requested release", func(t *testing.T) {
		spy := &entityPageGraphReleaseSource830G1Spy{pinned: snapshot}
		result, err := NewEntityPageGraphService830G1(spy).ReadPinnedEntityPage830G1(
			context.Background(), principal, scope, snapshot.ReleaseID, selector,
		)
		require.NoError(t, err)
		require.Equal(t, "pinned", result.ReadMode)
		require.Equal(t, []string{snapshot.ReleaseID}, spy.pinnedRelease)
		require.Zero(t, spy.currentCalls)
		require.Equal(t, 1, spy.pinnedCalls)
	})
}

func TestEntityPageGraphService830G1PinnedFailuresAreTypedAndNeverFallback(t *testing.T) {
	t.Parallel()
	snapshot := entityPageGraphReleaseFixture830G1(t)
	selector := EntityPageGraphSelector830G1{
		EntityID: "ping-an-e-sheng-bao", PageKind: "overview", StableKey: "overview",
	}
	principal := types.WikiReleasePrincipal{ID: "viewer", TenantID: 7, SpaceID: snapshotManifestSpace(t, snapshot)}
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: principal.SpaceID, RawKBID: "raw-596-1", WikiKBID: "8d5695de-f255-42d5-9a41-042ba86e97b9",
	}

	for _, test := range []struct {
		name string
		err  error
		want error
	}{
		{name: "nonexistent", err: ErrEntityPageGraphNotFound830G1, want: ErrEntityPageGraphNotFound830G1},
		{name: "foreign", err: ErrEntityPageGraphForbidden830G1, want: ErrEntityPageGraphForbidden830G1},
	} {
		t.Run(test.name, func(t *testing.T) {
			spy := &entityPageGraphReleaseSource830G1Spy{pinnedErr: test.err}
			_, err := NewEntityPageGraphService830G1(spy).ReadPinnedEntityPage830G1(
				context.Background(), principal, scope, "release-missing", selector,
			)
			require.ErrorIs(t, err, test.want)
			require.Zero(t, spy.currentCalls)
			require.Equal(t, 1, spy.pinnedCalls)
		})
	}

	for _, alias := range []string{"current", "latest"} {
		t.Run("reserved alias "+alias, func(t *testing.T) {
			spy := &entityPageGraphReleaseSource830G1Spy{}
			_, err := NewEntityPageGraphService830G1(spy).ReadPinnedEntityPage830G1(
				context.Background(), principal, scope, alias, selector,
			)
			require.ErrorIs(t, err, ErrEntityPageGraphNotFound830G1)
			require.Zero(t, spy.currentCalls)
			require.Zero(t, spy.pinnedCalls)
		})
	}

	t.Run("incomplete graph", func(t *testing.T) {
		incomplete := snapshot
		incomplete.Members = append([]types.WikiReleaseMemberSnapshot(nil), snapshot.Members[:len(snapshot.Members)-1]...)
		spy := &entityPageGraphReleaseSource830G1Spy{pinned: incomplete}
		_, err := NewEntityPageGraphService830G1(spy).ReadPinnedEntityPage830G1(
			context.Background(), principal, scope, snapshot.ReleaseID, selector,
		)
		require.ErrorIs(t, err, ErrEntityPageGraphIntegrity830G1)
		require.Zero(t, spy.currentCalls)
		require.Equal(t, 1, spy.pinnedCalls)
	})
}

func TestSchemaWikiServiceLoadEntityPageGraphRelease830G1RejectsManifestCustodyDrift(t *testing.T) {
	rawManifest := bytes.TrimSpace(loadEntityPageGraph830G1ServiceVector(t))
	manifest, err := types.ParseEntityPageManifest830G1(rawManifest)
	require.NoError(t, err)
	snapshot := entityPageGraphReleaseFixture830G1(t)

	db, err := gorm.Open(sqlite.Open(
		"file:entity-page-graph-830-g1-manifest-drift?mode=memory&cache=shared",
	), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.WikiReleasePreparation{}, &types.WikiRelease{}, &types.WikiReleaseMember{},
		&types.WikiReleaseHead{}, &types.WikiReleaseReceipt{},
	))
	repository := wikirepository.NewWikiReleaseRepository(db)
	scope := types.WikiReleaseScope{
		TenantID: 7, SpaceID: manifest.SpaceID, RawKBID: "raw-596-1", WikiKBID: manifest.WikiKBID,
	}
	principal := types.WikiReleasePrincipal{ID: "viewer", TenantID: 7, SpaceID: manifest.SpaceID}
	ctx := SealWikiReleaseAccess(context.Background(), principal, scope)
	releaseAuthority := NewWikiReleaseService(
		repository, NewContextWikiReleaseAccessVerifier(), nil, WikiReleaseServiceOptions{},
	)
	now := time.Unix(1_000, 0).UTC()
	manifestDigest := manifest.ManifestSHA256
	preparation := &types.WikiReleasePreparation{
		ID: "preparation-g1", WikiReleaseScope: scope,
		CandidateDigest: manifest.InputAuthority.CandidateSHA256, ManifestDigest: manifestDigest,
		ReadyReceiptDigest: "ready-g1", ReviewDecisionDigest: "review-g1", ReviewPolicyID: "policy-g1",
		Status:   types.WikiReleasePreparationReady,
		Manifest: append(json.RawMessage(nil), rawManifest...), Members: snapshot.Members, CreatedAt: now,
	}
	preparation.PreparationDigest = digestWikiReleasePreparation(preparation)
	release := &types.WikiRelease{
		ID: manifest.ReleaseID, WikiReleaseScope: scope,
		CandidateDigest: preparation.CandidateDigest, ManifestDigest: manifestDigest,
		PreparationID: preparation.ID, CreatedAt: now, ActivatedAt: now,
	}
	_, err = repository.Activate(ctx, wikirepository.WikiReleaseActivationWrite{
		Preparation: preparation, Release: release, Members: snapshot.Members,
		Nonce: "nonce-g1", AuthorizationDigest: "authorization-g1", ActivatedBy: principal.ID,
		ActivatedAt: now, ActivationReceiptID: "receipt-g1",
		ExpectedPreparationID: preparation.ID, ExpectedPreparationDigest: preparation.PreparationDigest,
	})
	require.NoError(t, err)

	tampered := manifest
	tampered.DisplayName += "（篡改）"
	tampered.ManifestSHA256 = entityPageGraphManifestDigest830G1ForTest(t, tampered)
	tamperedManifest, err := json.Marshal(tampered)
	require.NoError(t, err)
	result := db.Exec(
		"UPDATE wiki_release_preparations SET manifest = ? WHERE preparation_id = ?",
		string(tamperedManifest), preparation.ID,
	)
	require.NoError(t, result.Error)
	require.Equal(t, int64(1), result.RowsAffected)
	stored, err := repository.GetReadyPreparation(ctx, scope, preparation.ID)
	require.NoError(t, err)
	storedManifest, err := types.ParseEntityPageManifest830G1(stored.Manifest)
	require.NoError(t, err)
	require.Equal(t, tampered.DisplayName, storedManifest.DisplayName)
	require.Equal(t, tampered.ManifestSHA256, storedManifest.ManifestSHA256)
	require.Equal(t, manifestDigest, stored.ManifestDigest)
	require.NotEqual(t, stored.ManifestDigest, storedManifest.ManifestSHA256)

	_, err = NewSchemaWikiService(releaseAuthority, nil).LoadPinnedEntityPageGraphRelease830G1(
		ctx, principal, scope, manifest.ReleaseID,
	)
	require.ErrorIs(t, err, ErrEntityPageGraphIntegrity830G1)
}

func entityPageGraphManifestDigest830G1ForTest(t *testing.T, manifest types.EntityPageManifest830G1) string {
	t.Helper()
	raw, err := json.Marshal(manifest)
	require.NoError(t, err)
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var payload map[string]any
	require.NoError(t, decoder.Decode(&payload))
	delete(payload, "manifest_sha256")
	canonical := schemaWikiTestCanonicalJSON(t, payload)
	canonical = entityPageGraphUnescapeLineSeparators830G1ForTest(canonical)
	preimage := append([]byte("schema-wiki-canonical.v1\x00"+manifest.Contract+"\x00"), canonical...)
	sum := sha256.Sum256(preimage)
	return hex.EncodeToString(sum[:])
}

func entityPageGraphUnescapeLineSeparators830G1ForTest(encoded []byte) []byte {
	result := make([]byte, 0, len(encoded))
	for index := 0; index < len(encoded); index++ {
		if encoded[index] != '\\' || index+5 >= len(encoded) || encoded[index+1] != 'u' ||
			(string(encoded[index+2:index+6]) != "2028" && string(encoded[index+2:index+6]) != "2029") {
			result = append(result, encoded[index])
			continue
		}
		slashes := 1
		for previous := index - 1; previous >= 0 && encoded[previous] == '\\'; previous-- {
			slashes++
		}
		if slashes%2 == 0 {
			result = append(result, encoded[index])
			continue
		}
		if encoded[index+5] == '8' {
			result = append(result, []byte("\u2028")...)
		} else {
			result = append(result, []byte("\u2029")...)
		}
		index += 5
	}
	return result
}

func snapshotManifestSpace(t *testing.T, snapshot EntityPageGraphReleaseSnapshot830G1) string {
	t.Helper()
	manifest, err := types.ParseEntityPageManifest830G1(snapshot.Manifest)
	require.NoError(t, err)
	return manifest.SpaceID
}

func readServiceTestFile(t *testing.T, path string) []byte {
	t.Helper()
	raw, err := os.ReadFile(path)
	require.NoError(t, err)
	return raw
}
