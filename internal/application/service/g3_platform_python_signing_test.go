package service

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestG3PlatformPythonSignedAuthorityWireVector(t *testing.T) {
	raw, err := os.ReadFile("../../../harness/tests/fixtures/product_ingestion/python-signing-v1.json")
	require.NoError(t, err)
	var fixture struct {
		FixtureOnly       bool   `json:"fixture_only"`
		SystemKeyID       string `json:"system_key_id"`
		SystemPublicKey   string `json:"system_public_key_b64"`
		PublishKeyID      string `json:"publish_key_id"`
		PublishPublicKey  string `json:"publish_public_key_b64"`
		DecisionJSON      string `json:"decision_json"`
		AuthorizationJSON string `json:"authorization_json"`
	}
	require.NoError(t, json.Unmarshal(raw, &fixture))
	require.True(t, fixture.FixtureOnly)
	systemKey, err := base64.StdEncoding.DecodeString(fixture.SystemPublicKey)
	require.NoError(t, err)
	publishKey, err := base64.StdEncoding.DecodeString(fixture.PublishPublicKey)
	require.NoError(t, err)
	decision, err := ParseSystemPolicyDecisionReceiptV1([]byte(fixture.DecisionJSON))
	require.NoError(t, err)
	canonical, err := CanonicalSystemPolicyDecisionReceiptV1(decision, true)
	require.NoError(t, err)
	require.Equal(t, fixture.DecisionJSON, string(canonical))
	require.NoError(t, NewEd25519SystemPolicyDecisionVerifier(map[string]ed25519.PublicKey{fixture.SystemKeyID: systemKey}).Verify(decision))
	authorization, err := ParsePublishAuthorizationV0([]byte(fixture.AuthorizationJSON))
	require.NoError(t, err)
	canonical, err = CanonicalPublishAuthorizationV0(authorization, true)
	require.NoError(t, err)
	require.Equal(t, fixture.AuthorizationJSON, string(canonical))
	require.NoError(t, NewEd25519WikiReleaseAuthorizationVerifier(map[string]ed25519.PublicKey{fixture.PublishKeyID: publishKey}).Verify(authorization))
	digest := sha256.Sum256([]byte(fixture.DecisionJSON))
	require.Equal(t, hex.EncodeToString(digest[:]), authorization.ReviewDecisionDigest)
	require.Equal(t, decision.InnerReviewPolicyID, authorization.ReviewPolicyID)
	decision.Nonce += "changed"
	require.Error(t, NewEd25519SystemPolicyDecisionVerifier(map[string]ed25519.PublicKey{fixture.SystemKeyID: systemKey}).Verify(decision))
	authorization.Nonce += "changed"
	require.Error(t, NewEd25519WikiReleaseAuthorizationVerifier(map[string]ed25519.PublicKey{fixture.PublishKeyID: publishKey}).Verify(authorization))
}
