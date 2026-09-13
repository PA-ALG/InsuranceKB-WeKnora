package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"github.com/stretchr/testify/require"
	"strings"
	"testing"
)

func TestG3PlatformSnapshotSignerMatchesPythonWireVector(t *testing.T) {
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{81}, 32))
	signer, err := NewEd25519G3PlatformSnapshotSigner("fixture-key", key)
	require.NoError(t, err)
	key[0] ^= 1
	// Fixed seed vector generated with Python cryptography Ed25519PrivateKey;
	// Python transport uses standard base64 of domain UTF-8 + NUL + ASCII SHA.
	for domain, want := range map[string]string{G3PlatformSourceSnapshotSigningDomainV1: "/2iensALxNMSAxC+th4rZIFXRNGqWYmj7B7sy7S95lZvIA+/XBpHALs99m4e2+IrKPQikPZ3nzgr5atKu3ZcBQ==", G3PlatformBaseSnapshotSigningDomainV1: "xaXG5gL4TvKf9hLTZSC/+xqDnK5/7FwticE4CDbzkm8wqdY9RVLGTVs7BDyAGP/jnKJ7aEgozyPhG3obDERwBw=="} {
		id, sig, err := signer.SignG3PlatformSnapshot(context.Background(), domain, strings.Repeat("a", 64))
		require.NoError(t, err)
		require.Equal(t, "fixture-key", id)
		require.Equal(t, want, base64.StdEncoding.EncodeToString(sig))
		raw, err := json.Marshal(G3PlatformSnapshotAuthorityV1{Signature: sig})
		require.NoError(t, err)
		require.Contains(t, string(raw), `"signature":"`+want+`"`)
	}
}
func TestG3PlatformSnapshotSignerRejectsOtherDomainsAndMalformedInput(t *testing.T) {
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{81}, 32))
	signer, err := NewEd25519G3PlatformSnapshotSigner("fixture-key", key)
	require.NoError(t, err)
	for _, tc := range []struct{ domain, digest string }{{"system-policy-decision.v1", strings.Repeat("a", 64)}, {G3PlatformSourceSnapshotSigningDomainV1, strings.Repeat("A", 64)}, {G3PlatformBaseSnapshotSigningDomainV1, "abc"}} {
		_, sig, err := signer.SignG3PlatformSnapshot(context.Background(), tc.domain, tc.digest)
		require.Error(t, err)
		require.Empty(t, sig)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, sig, err := signer.SignG3PlatformSnapshot(ctx, G3PlatformSourceSnapshotSigningDomainV1, strings.Repeat("a", 64))
	require.Error(t, err)
	require.Empty(t, sig)
	for _, k := range []ed25519.PrivateKey{nil, key[:32], append(append(ed25519.PrivateKey{}, key[:63]...), key[63]^1)} {
		_, err := NewEd25519G3PlatformSnapshotSigner("fixture-key", k)
		require.Error(t, err)
	}
	_, err = NewEd25519G3PlatformSnapshotSigner("", key)
	require.Error(t, err)
}
