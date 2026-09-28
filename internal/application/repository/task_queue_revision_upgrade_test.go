package repository

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestUPGFinalizingSeedFencesRevisionAtomically(t *testing.T) {
	for _, mode := range []string{"matching", "stale_attempt", "different_file", "invalid_binding"} {
		t.Run(mode, func(t *testing.T) {
			db, seeder := setupFinalizingPendingOpTest(t)
			require.NoError(
				t,
				db.Exec("ALTER TABLE knowledges ADD COLUMN current_parse_attempt INTEGER DEFAULT 0").Error,
			)
			require.NoError(t, db.Exec("ALTER TABLE knowledges ADD COLUMN file_sha256 TEXT DEFAULT ''").Error)
			binding := testRevisionBinding(2)
			require.NoError(
				t,
				db.Exec("UPDATE knowledges SET current_parse_attempt=2,file_sha256=?", binding.FileSHA256).Error,
			)
			switch mode {
			case "stale_attempt":
				binding.ParseAttempt = 1
			case "different_file":
				binding.FileSHA256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
			case "invalid_binding":
				binding.FileSHA256 = "bad"
			}
			payload, err := json.Marshal(struct {
				Revision *types.RevisionCommitBinding `json:"revision"`
			}{&binding})
			require.NoError(t, err)
			op := makePendingOp(
				types.TypeWikiIngest,
				types.TaskScopeKnowledgeBase,
				"kb-1",
				"ingest",
				"knowledge-1",
				payload,
			)
			promoted, err := seeder.SeedKnowledgeFinalizingWithPendingOp(context.Background(), "knowledge-1", 3, op)
			if mode == "invalid_binding" {
				require.Error(t, err)
			} else {
				require.NoError(t, err)
			}
			require.Equal(t, mode == "matching", promoted)
			var count int64
			require.NoError(t, db.Model(&types.TaskPendingOp{}).Count(&count).Error)
			want := int64(0)
			if mode == "matching" {
				want = 1
			}
			require.Equal(t, want, count)
			var status string
			require.NoError(t, db.Raw("SELECT parse_status FROM knowledges WHERE id='knowledge-1'").Scan(&status).Error)
			if mode != "matching" {
				require.Equal(t, types.ParseStatusProcessing, status)
			}
		})
	}
}
