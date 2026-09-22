package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/hex"
	"strings"
)

type ed25519G3PlatformSnapshotSigner struct {
	keyID string
	key   ed25519.PrivateKey
}

// NewEd25519G3PlatformSnapshotSigner copies the source-custody key. This key
// cannot sign system review or publication authority through this port.
func NewEd25519G3PlatformSnapshotSigner(keyID string, key ed25519.PrivateKey) (G3PlatformSnapshotSigner, error) {
	if keyID == "" || strings.TrimSpace(keyID) != keyID || strings.IndexFunc(keyID, func(r rune) bool { return r < 0x20 || r == 0x7f }) >= 0 ||
		len(key) != ed25519.PrivateKeySize || !bytes.Equal(key, ed25519.NewKeyFromSeed(key[:ed25519.SeedSize])) {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	return &ed25519G3PlatformSnapshotSigner{keyID: keyID, key: append(ed25519.PrivateKey(nil), key...)}, nil
}
func (s *ed25519G3PlatformSnapshotSigner) SignG3PlatformSnapshot(ctx context.Context, domain, digest string) (string, []byte, error) {
	if s == nil || ctx == nil || ctx.Err() != nil || (domain != G3PlatformSourceSnapshotSigningDomainV1 && domain != G3PlatformBaseSnapshotSigningDomainV1) || len(digest) != 64 || strings.ToLower(digest) != digest {
		return "", nil, ErrG3PlatformSnapshotUnavailable
	}
	if _, err := hex.DecodeString(digest); err != nil {
		return "", nil, ErrG3PlatformSnapshotUnavailable
	}
	return s.keyID, ed25519.Sign(s.key, []byte(domain+"\x00"+digest)), nil
}
