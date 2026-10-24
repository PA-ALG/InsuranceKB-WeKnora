package service

import (
	"bytes"
	"crypto/ed25519"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/capture"
)

// captureTestKeys is a fixed signing ring for first-parse captures in tests (S7d-2c-3b).
func captureTestKeys(t *testing.T) *capture.Keys {
	t.Helper()
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x63}, ed25519.SeedSize))
	return capture.NewKeys("capture-test-key", map[string]ed25519.PrivateKey{"capture-test-key": key})
}
