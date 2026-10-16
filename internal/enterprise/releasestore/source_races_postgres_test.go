package releasestore

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

type raceActorKey struct{}

// Pause after the first actor has acquired a real row lock; release it only
// when the other actor has reached its competing query. No production hooks
// or timing assumptions are needed.
func raceOnKnowledge(
	t *testing.T, db *gorm.DB, first, second func(context.Context) error,
) (error, error) {
	t.Helper()
	return raceOnRow(t, db, "knowledges", first, second)
}

func raceOnRow(
	t *testing.T, db *gorm.DB, table string, first, second func(context.Context) error,
) (error, error) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	held, attempted, proceed := make(chan struct{}), make(chan struct{}), make(chan struct{})
	var holdOnce, attemptOnce, proceedOnce sync.Once
	unblock := func() { proceedOnce.Do(func() { close(proceed) }) }
	defer unblock()
	require.NoError(t, db.Callback().Query().After("gorm:query").Register("test_hold_knowledge", func(tx *gorm.DB) {
		if tx.Statement.Table == table && tx.Error == nil &&
			tx.Statement.Context.Value(raceActorKey{}) == "first" {
			holdOnce.Do(func() {
				close(held)
				select {
				case <-proceed:
				case <-ctx.Done():
				}
			})
		}
	}))
	require.NoError(t, db.Callback().Query().Before("gorm:query").Register("test_attempt_knowledge", func(tx *gorm.DB) {
		if tx.Statement.Table == table && tx.Statement.Context.Value(raceActorKey{}) == "second" {
			attemptOnce.Do(func() { close(attempted) })
		}
	}))
	t.Cleanup(func() {
		require.NoError(t, db.Callback().Query().Remove("test_hold_knowledge"))
		require.NoError(t, db.Callback().Query().Remove("test_attempt_knowledge"))
	})
	firstDone, secondDone := make(chan error, 1), make(chan error, 1)
	go func() { firstDone <- first(context.WithValue(ctx, raceActorKey{}, "first")) }()
	select {
	case <-held:
	case err := <-firstDone:
		t.Fatalf("first actor finished without locking %s: %v", table, err)
	case <-ctx.Done():
		t.Fatal("first actor did not lock the row")
	}
	go func() { secondDone <- second(context.WithValue(ctx, raceActorKey{}, "second")) }()
	select {
	case <-attempted:
	case err := <-secondDone:
		t.Fatalf("second actor finished without querying %s: %v", table, err)
	case <-ctx.Done():
		t.Fatal("second actor did not reach the competing row query")
	}
	unblock()
	return <-firstDone, <-secondDone
}

func TestPostgresActivationAndKnowledgeDeletionSerialize(t *testing.T) {
	for _, deletionFirst := range []bool{false, true} {
		t.Run(map[bool]string{false: "activation first", true: "deletion first"}[deletionFirst], func(t *testing.T) {
			db := openSchema(t)
			store := New(db, testSpaces(t))
			write := activation(t, store, "race", postgresSourceRef)
			activate := func(ctx context.Context) error { _, err := store.Activate(ctx, write); return err }
			remove := func(ctx context.Context) error {
				return repository.NewKnowledgeRepository(db).DeleteKnowledge(ctx, 7, "k-1")
			}
			first, second := activate, remove
			if deletionFirst {
				first, second = remove, activate
			}
			firstErr, secondErr := raceOnKnowledge(t, db, first, second)
			require.NoError(t, firstErr)
			if deletionFirst {
				var failure *release.Error
				require.ErrorAs(t, secondErr, &failure)
				require.Equal(t, release.ErrorSourceUnavailable, failure.Code)
				require.Zero(t, rowCounts(t, db)["wiki_releases"])
			} else {
				require.ErrorIs(t, secondErr, repository.ErrResourcePinned)
				require.Equal(t, "pinned", retention(t, db, "k-1"))
			}
		})
	}
}

func TestPostgresActivationAndActiveRetirementRecheckHeadUnderLock(t *testing.T) {
	for _, retirementFirst := range []bool{false, true} {
		name := map[bool]string{false: "activation first", true: "retirement first"}[retirementFirst]
		t.Run(name, func(t *testing.T) {
			db := openSchema(t)
			store := New(db, testSpaces(t))
			active, err := store.Activate(context.Background(), activation(t, store, "first", postgresSourceRef))
			require.NoError(t, err)
			write := activation(t, store, "next", postgresSourceRef)
			activate := func(ctx context.Context) error { _, err := store.Activate(ctx, write); return err }
			retire := func(ctx context.Context) error {
				_, err := store.Retire(ctx, release.RetirementWrite{
					TenantID: 7, SpaceID: "space-1", ReleaseID: active.ID, Reason: "done", Subject: "admin",
				})
				return err
			}
			first, second := activate, retire
			if retirementFirst {
				first, second = retire, activate
			}
			firstErr, secondErr := raceOnKnowledge(t, db, first, second)
			if retirementFirst {
				var failure *release.Error
				require.ErrorAs(t, firstErr, &failure)
				require.Equal(t, release.ErrorReleaseActive, failure.Code)
			} else {
				require.NoError(t, firstErr)
			}
			require.NoError(t, secondErr)
			require.Equal(t, "pinned", retention(t, db, "k-1"))
			pins, err := store.SourcePins(context.Background(), 7, "space-1", "k-1")
			require.NoError(t, err)
			var activePins int
			for _, pin := range pins {
				if pin.Active {
					activePins++
				}
			}
			require.Equal(t, 1, activePins)
		})
	}
}

func TestPostgresKnowledgeBaseDeletionAndActivationSerialize(t *testing.T) {
	for _, deletionFirst := range []bool{false, true} {
		t.Run(map[bool]string{false: "activation first", true: "KB deletion first"}[deletionFirst], func(t *testing.T) {
			db := openSchema(t)
			store := New(db, testSpaces(t))
			write := activation(t, store, "kb-race", postgresSourceRef)
			activate := func(ctx context.Context) error { _, err := store.Activate(ctx, write); return err }
			remove := func(ctx context.Context) error {
				return repository.NewKnowledgeRepository(db).DeleteKnowledgeBaseUnlessPinned(ctx, 7, "raw-1")
			}
			first, second := activate, remove
			if deletionFirst {
				first, second = remove, activate
			}
			firstErr, secondErr := raceOnRow(t, db, "knowledge_bases", first, second)
			require.NoError(t, firstErr)
			var kb struct{ DeletedAt *time.Time }
			require.NoError(t, db.Table("knowledge_bases").Where("id = 'raw-1'").Take(&kb).Error)
			if deletionFirst {
				var failure *release.Error
				require.ErrorAs(t, secondErr, &failure)
				require.Equal(t, release.ErrorSourceUnavailable, failure.Code)
				require.NotNil(t, kb.DeletedAt)
				require.Zero(t, rowCounts(t, db)["wiki_releases"])
			} else {
				require.ErrorIs(t, secondErr, repository.ErrResourcePinned)
				require.Nil(t, kb.DeletedAt)
				require.Equal(t, "pinned", retention(t, db, "k-1"))
			}
		})
	}
}

func TestPostgresBindingSealAndKnowledgeBaseDeletionSerialize(t *testing.T) {
	for _, deletionFirst := range []bool{false, true} {
		t.Run(map[bool]string{false: "seal first", true: "KB deletion first"}[deletionFirst], func(t *testing.T) {
			db := openSchema(t)
			var source types.KnowledgeRevisionSource
			require.NoError(t, db.Where("knowledge_id = 'k-1'").Take(&source).Error)
			pages := 1
			source.PageCount, source.RetentionState, source.ReleasedAt = &pages, "pinned", nil
			var err error
			source.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(source)
			require.NoError(t, err)
			repo := repository.NewKnowledgeRepository(db)
			seal := func(ctx context.Context) error {
				_, err := repo.(interfaces.KnowledgeRevisionSourceRepository).SealRevisionSourceBinding(ctx, source)
				return err
			}
			remove := func(ctx context.Context) error { return repo.DeleteKnowledgeBaseUnlessPinned(ctx, 7, "raw-1") }
			first, second := seal, remove
			if deletionFirst {
				first, second = remove, seal
			}
			firstErr, secondErr := raceOnRow(t, db, "knowledge_bases", first, second)
			require.NoError(t, firstErr)
			if deletionFirst {
				require.ErrorIs(t, secondErr, repository.ErrRevisionCommitFailed)
				require.Equal(t, "released", retention(t, db, "k-1"))
			} else {
				require.ErrorIs(t, secondErr, repository.ErrResourcePinned)
				require.Equal(t, "pinned", retention(t, db, "k-1"))
			}
		})
	}
}
