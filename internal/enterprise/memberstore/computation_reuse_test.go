package memberstore_test

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/memberstore"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

type projectionCounter struct {
	logger.Interface
	calls atomic.Int64
}

func (l *projectionCounter) Trace(_ context.Context, _ time.Time, query func() (string, int64), _ error) {
	sql, _ := query()
	if strings.Contains(sql, "jsonb_array_elements") {
		l.calls.Add(1)
	}
}

func TestPostgresMemberComputationReuseDoesNotTrustCachedStorage(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	counter := &projectionCounter{Interface: logger.Default.LogMode(logger.Silent)}
	measured := db.Session(&gorm.Session{Logger: counter})
	store := memberstore.New()
	repo := repository.NewWikiReleaseRepository(measured).WithMemberStorage(store)
	input := make([]types.WikiReleaseMemberSnapshot, 1000)
	for i := range input {
		input[i] = types.WikiReleaseMemberSnapshot{
			Kind:        "page",
			LogicalSlug: fmt.Sprintf("item/%06d", i), MemberDigest: strings.Repeat("a",
				64), Content: "unchanged original bytes", Payload: json.RawMessage(`{"number":9007199254740993}`),
		}
	}
	publish := func(id, parent string, epoch uint64) error {
		p := types.WikiReleasePreparation{
			ID: "p-" + id, WikiReleaseScope: scope(),
			Status: "ready", CandidateDigest: id, ManifestDigest: id,
			PreparationDigest: id, ExpectedReleaseID: parent, ExpectedActivationEpoch: epoch,
			Manifest: json.RawMessage(`{}`), Members: input,
		}
		r := types.WikiRelease{
			ID: id, WikiReleaseScope: scope(),
			CandidateDigest: id, ManifestDigest: id, PreparationID: p.ID,
		}
		_, err := repo.Activate(ctx, repository.WikiReleaseActivationWrite{
			Preparation: &p,
			Release:     &r, Members: input, ExpectedReleaseID: parent,
			ExpectedActivationEpoch: epoch, ExpectedPreparationID: p.ID,
			ExpectedPreparationDigest: p.PreparationDigest, Nonce: id,
			ActivationReceiptID: "receipt-" + id,
		})
		return err
	}
	require.NoError(t, publish("one", "", 0))
	require.Positive(t, counter.calls.Load())
	counter.calls.Store(0)
	require.NoError(t, publish("two", "one", 1))
	require.Zero(t, counter.calls.Load(), "exact unchanged inputs should reuse canonical computations")
	require.NoError(t, db.Exec("UPDATE enterprise_member_contents SET title='damaged' WHERE logic"+
		"al_slug='item/000001'").
		Error)
	require.Error(t, publish("three", "two", 2), "a computation memo is not proof that a stored object is intact")
	var count int64
	require.NoError(t, db.Table("wiki_releases").Count(&count).Error)
	require.EqualValues(t, 2, count)
	// The opaque source rows still restore and preserve their large integer projection.
	require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET title='' WHERE logical_slug='item/000001'`).Error)
	require.NoError(t, publish("four", "two", 2))
}
