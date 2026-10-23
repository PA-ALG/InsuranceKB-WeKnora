package capture

import (
	"crypto/ed25519"
	"encoding/json"
)

// signingDomain separates capture seals from every other use of the signing ring. Frozen.
const signingDomain = "weknora.concept-source-reuse.830.g3.v1"

// Keys is the deployment's citation-token signing ring: the active key seals, any key in the
// ring opens, so a rotated key keeps older captures readable.
type Keys struct {
	activeKeyID string
	private     map[string]ed25519.PrivateKey
	public      map[string]ed25519.PublicKey
}

// NewKeys copies the ring; keys of the wrong size are ignored and cannot seal or open.
func NewKeys(activeKeyID string, privateKeys map[string]ed25519.PrivateKey) *Keys {
	keys := &Keys{
		activeKeyID: activeKeyID,
		private:     map[string]ed25519.PrivateKey{},
		public:      map[string]ed25519.PublicKey{},
	}
	for id, key := range privateKeys {
		if len(key) != ed25519.PrivateKeySize {
			continue
		}
		keys.private[id] = append(ed25519.PrivateKey(nil), key...)
		keys.public[id] = append(ed25519.PublicKey(nil), key.Public().(ed25519.PublicKey)...)
	}
	return keys
}

type seal struct {
	KeyID     string          `json:"key_id"`
	Key       string          `json:"key"`
	Payload   json.RawMessage `json:"payload"`
	Signature []byte          `json:"signature"`
}

func signedBytes(key string, payload []byte) []byte {
	return append([]byte(signingDomain+"\n"+key+"\n"), payload...)
}

func (k *Keys) seal(key string, payload []byte) ([]byte, error) {
	if k == nil || key == "" {
		return nil, ErrUnavailable
	}
	private := k.private[k.activeKeyID]
	if len(private) != ed25519.PrivateKeySize {
		return nil, ErrUnavailable
	}
	normalized, err := json.Marshal(json.RawMessage(payload))
	if err != nil {
		return nil, err
	}
	return json.Marshal(seal{
		KeyID: k.activeKeyID, Key: key, Payload: normalized,
		Signature: ed25519.Sign(private, signedBytes(key, normalized)),
	})
}

func (k *Keys) open(key string, encoded []byte) ([]byte, error) {
	var s seal
	if k == nil || key == "" || json.Unmarshal(encoded, &s) != nil || s.Key != key {
		return nil, ErrUnavailable
	}
	public := k.public[s.KeyID]
	if len(public) != ed25519.PublicKeySize || !ed25519.Verify(public, signedBytes(key, s.Payload), s.Signature) {
		return nil, ErrUnavailable
	}
	return s.Payload, nil
}
