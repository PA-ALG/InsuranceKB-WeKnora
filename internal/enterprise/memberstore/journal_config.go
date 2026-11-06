package memberstore

import (
	"context"
	"os"
	"strconv"
	"time"
)

const journalTimeoutEnvironment = "ENTERPRISE_MEMBER_JOURNAL_TIMEOUT_SECONDS"

// A zero policy is invalid. Each Store and its attempts retain the construction-time
// value, including while a retained validation outlives the initiating request.
type journalPolicy struct {
	writeTimeout time.Duration
}

func newJournalPolicy() journalPolicy {
	value, set := os.LookupEnv(journalTimeoutEnvironment)
	if !set {
		return journalPolicy{writeTimeout: 15 * time.Second}
	}
	if len(value) == 0 || len(value) > 2 || value[0] < '1' || value[0] > '9' {
		return journalPolicy{}
	}
	if len(value) == 2 && (value[1] < '0' || value[1] > '9') {
		return journalPolicy{}
	}
	seconds, err := strconv.Atoi(value)
	if err != nil || seconds > 60 {
		return journalPolicy{}
	}
	return journalPolicy{writeTimeout: time.Duration(seconds) * time.Second}
}

func (p journalPolicy) valid() bool { return p.writeTimeout > 0 }

func (p journalPolicy) writeContext(ctx context.Context) (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.WithoutCancel(ctx), p.writeTimeout)
}

func (p journalPolicy) readContext(ctx context.Context) (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.WithoutCancel(ctx), min(p.writeTimeout, 5*time.Second))
}
