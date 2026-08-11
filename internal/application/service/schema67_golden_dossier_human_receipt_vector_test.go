package service

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

type schema67GoldenDossierHumanReceiptVector struct {
	PublicKeyID           string `json:"public_key_id"`
	PublicKeyBase64       string `json:"public_key_base64"`
	ReviewPolicySHA256    string `json:"review_policy_sha256"`
	SubjectPreimageBase64 string `json:"subject_preimage_base64"`
	SubjectSHA256         string `json:"subject_sha256"`
	ReceiptJSON           string `json:"receipt_json"`
	ReceiptSHA256         string `json:"receipt_sha256"`
}

func TestSchema67GoldenDossierHumanReceiptVector(t *testing.T) {
	raw, err := os.ReadFile("testdata/122_schema67_golden_dossier_human_receipt_vector.json")
	require.NoError(t, err)
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var vector schema67GoldenDossierHumanReceiptVector
	require.NoError(t, decoder.Decode(&vector))
	var trailing any
	require.ErrorIs(t, decoder.Decode(&trailing), io.EOF)

	preimage, err := base64.StdEncoding.DecodeString(vector.SubjectPreimageBase64)
	require.NoError(t, err)
	preimageDigest := sha256.Sum256(preimage)
	require.Equal(t, vector.SubjectSHA256, hex.EncodeToString(preimageDigest[:]))

	receiptRaw := []byte(vector.ReceiptJSON)
	receiptDigest := sha256.Sum256(receiptRaw)
	require.Equal(t, vector.ReceiptSHA256, hex.EncodeToString(receiptDigest[:]))
	receipt, err := ParseHumanBatchDecisionReceiptV1(receiptRaw)
	require.NoError(t, err)
	require.Equal(t, vector.SubjectSHA256, receipt.HumanBatchHash)
	require.Equal(t, vector.ReviewPolicySHA256, receipt.ReviewPolicyHash)
	require.Equal(t, vector.PublicKeyID, receipt.SignerKeyID)
	canonical, err := CanonicalHumanBatchDecisionReceiptV1(receipt, true)
	require.NoError(t, err)
	require.Equal(t, receiptRaw, canonical)

	publicKey, err := base64.RawURLEncoding.DecodeString(vector.PublicKeyBase64)
	require.NoError(t, err)
	require.Len(t, publicKey, ed25519.PublicKeySize)
	verifier := NewEd25519HumanBatchDecisionVerifier(map[string]ed25519.PublicKey{
		vector.PublicKeyID: publicKey,
	})
	require.NoError(t, verifier.Verify(receipt))
}
