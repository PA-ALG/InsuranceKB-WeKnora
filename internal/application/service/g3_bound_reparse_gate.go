package service

import (
	"encoding/json"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
)

func g3BoundReparseReceipt(knowledge *types.Knowledge, key string) (types.G3BoundReparseReceipt, bool) {
	var empty types.G3BoundReparseReceipt
	if knowledge == nil || key == "" {
		return empty, false
	}
	var metadata map[string]json.RawMessage
	if json.Unmarshal(knowledge.Metadata, &metadata) != nil {
		return empty, false
	}
	var receipts map[string]types.G3BoundReparseReceipt
	if json.Unmarshal(metadata["product_ingestion_recoveries"], &receipts) != nil {
		return empty, false
	}
	receipt, ok := receipts[key]
	if !ok || receipt.Contract != types.G3BoundReparseContractV1 || receipt.KnowledgeID != knowledge.ID || receipt.RecoveryKey != key {
		return empty, false
	}
	return receipt, true
}

func g3BoundReparseTaskAllowed(knowledge *types.Knowledge, payload types.DocumentProcessPayload, now time.Time) bool {
	if payload.RecoveryKey == "" {
		return true
	}
	receipt, ok := g3BoundReparseReceipt(knowledge, payload.RecoveryKey)
	if !ok || receipt.ParseAttempt != payload.ParseAttempt || knowledge.CurrentParseAttempt != payload.ParseAttempt ||
		now.After(receipt.DeadlineAt) || now.Equal(receipt.DeadlineAt) {
		return false
	}
	return receipt.DispatchState == "dispatching" || receipt.DispatchState == "enqueued" || receipt.DispatchState == "unknown"
}
