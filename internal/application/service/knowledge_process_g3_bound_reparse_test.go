package service

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestG3BoundReparseTaskGateRejectsExpiredOrSupersededGeneration(t *testing.T) {
	now := time.Now().UTC()
	key := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	receipt := types.G3BoundReparseReceipt{Contract: types.G3BoundReparseContractV1, RunID: "original", Ordinal: 0, KnowledgeID: "source", ExpectedParseAttempt: 3, ParseAttempt: 4, RecoveryKey: key, DeadlineAt: now.Add(time.Minute), DispatchState: "dispatching"}
	metadata, err := json.Marshal(map[string]any{"product_ingestion_recoveries": map[string]any{key: receipt}})
	require.NoError(t, err)
	knowledge := &types.Knowledge{ID: "source", CurrentParseAttempt: 4, ParseStatus: "pending", Metadata: types.JSON(metadata)}
	payload := types.DocumentProcessPayload{KnowledgeID: "source", ParseAttempt: 4, RecoveryKey: key}
	require.True(t, g3BoundReparseTaskAllowed(knowledge, payload, now))
	require.False(t, g3BoundReparseTaskAllowed(knowledge, payload, now.Add(2*time.Minute)))
	knowledge.CurrentParseAttempt = 5
	require.False(t, g3BoundReparseTaskAllowed(knowledge, payload, now))
}
