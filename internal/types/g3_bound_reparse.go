package types

import "time"

const G3BoundReparseContractV1 = "g3-platform-bound-reparse.830.v1"

// G3BoundReparseReceipt binds one recovery request to one parse generation.
type G3BoundReparseReceipt struct {
	Contract             string    `json:"contract"`
	RunID                string    `json:"run_id"`
	Ordinal              int       `json:"ordinal"`
	KnowledgeID          string    `json:"knowledge_id"`
	ExpectedParseAttempt int64     `json:"expected_parse_attempt"`
	ParseAttempt         int64     `json:"parse_attempt"`
	RecoveryKey          string    `json:"recovery_key"`
	DeadlineAt           time.Time `json:"deadline_at"`
	DispatchState        string    `json:"dispatch_state"`
	QueueTaskID          *string   `json:"queue_task_id"`
	ParseStatus          string    `json:"parse_status"`
}
