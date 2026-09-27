package types

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func originCorpus830G3(t *testing.T, merged BatchCorpus830G3, bindings []MaterialBinding830G3) BatchCorpus830G3 {
	t.Helper()
	byID := map[string]CorpusEntry830G3{}
	for _, entry := range merged.Entries {
		byID[entry.MaterialID] = entry
	}
	origin := merged
	origin.Entries = make([]CorpusEntry830G3, 0, len(bindings))
	for _, binding := range bindings {
		origin.Entries = append(origin.Entries, byID[binding.MaterialID])
	}
	digest, err := batchConceptHashWithout830G3(origin.Contract, origin, "corpus_sha256")
	require.NoError(t, err)
	origin.CorpusSHA256 = digest
	return origin
}

func TestModelReceiptGroupsRetainOriginalOriginCorpusHashes830G3(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &bundle))
	typed, err := decodeResolutionInputs830G3(bundle.Request.ResolutionInputs, bundle.Request.Resolution)
	require.NoError(t, err)
	require.Len(t, typed.Proposals.ModelReceipts, 1)
	receipt := typed.Proposals.ModelReceipts[0]
	require.Greater(t, len(receipt.MaterialBindings), 1)

	first := receipt
	first.MaterialBindings = append([]MaterialBinding830G3(nil), receipt.MaterialBindings[:1]...)
	first.RequestSHA256 = "1d982fd8c4d4a5a8d8d74a2145a69f63df77752464d3f80ac65dc94e5a9d12a1"

	second := receipt
	second.MaterialBindings = append([]MaterialBinding830G3(nil), receipt.MaterialBindings[1:2]...)
	second.RequestSHA256 = "d92b5a9fcce40474ed10524df3f9f4a064fe9ce43e9f247e2b3c086beb9c33ed"
	firstOriginBindings := append(append([]MaterialBinding830G3(nil), first.MaterialBindings...), second.MaterialBindings...)
	firstOrigin := originCorpus830G3(t, bundle.Request.ResolutionInputs.Corpus, firstOriginBindings)
	first.InputSHA256, err = batchConceptHash830G3("batch-classifier-input.830.g3.v1", map[string]any{
		"corpus_sha256": firstOrigin.CorpusSHA256, "material_bindings": first.MaterialBindings,
	})
	require.NoError(t, err)
	second.InputSHA256, err = batchConceptHash830G3("batch-classifier-input.830.g3.v1", map[string]any{
		"corpus_sha256": firstOrigin.CorpusSHA256, "material_bindings": second.MaterialBindings,
	})
	require.NoError(t, err)

	third := receipt
	third.MaterialBindings = append([]MaterialBinding830G3(nil), receipt.MaterialBindings[2:]...)
	third.RequestSHA256 = "02c7a828c6dc1b001f099ec08a86beeb98b906437bcadbca761e953795c21745"
	thirdPermit := *third.PolicyReceipt.PermitView
	third.PolicyReceipt.PermitView = &thirdPermit
	third.PolicyReceipt.AdmissionHash = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
	third.PolicyReceipt.PermitView.AdmissionHash = third.PolicyReceipt.AdmissionHash
	thirdPermitDigest, err := permitDigest830G3(*third.PolicyReceipt.PermitView)
	require.NoError(t, err)
	third.PolicyReceipt.PermitDigest = &thirdPermitDigest
	thirdOrigin := originCorpus830G3(t, bundle.Request.ResolutionInputs.Corpus, third.MaterialBindings)
	third.InputSHA256, err = batchConceptHash830G3("batch-classifier-input.830.g3.v1", map[string]any{
		"corpus_sha256": thirdOrigin.CorpusSHA256, "material_bindings": third.MaterialBindings,
	})
	require.NoError(t, err)
	require.NoError(t, validatePolicyReceipt830G3(first.PolicyReceipt))
	require.NoError(t, validatePolicyReceipt830G3(second.PolicyReceipt))
	require.NoError(t, validatePolicyReceipt830G3(third.PolicyReceipt))

	proposals := typed.Proposals
	proposals.ModelReceipts = []ModelReceiptBinding830G3{first, second, third}
	entries, _, err := corpusIndexes830G3(bundle.Request.ResolutionInputs.Corpus)
	require.NoError(t, err)
	valid := validModelReceiptRequests830G3(proposals, bundle.Request.ResolutionInputs.Corpus, entries)
	require.True(t, valid[first.RequestSHA256])
	require.True(t, valid[second.RequestSHA256])
	require.True(t, valid[third.RequestSHA256])

	overlap := third
	overlap.MaterialBindings = append([]MaterialBinding830G3(nil), first.MaterialBindings...)
	overlapOrigin := originCorpus830G3(t, bundle.Request.ResolutionInputs.Corpus, overlap.MaterialBindings)
	overlap.InputSHA256, err = batchConceptHash830G3("batch-classifier-input.830.g3.v1", map[string]any{
		"corpus_sha256": overlapOrigin.CorpusSHA256, "material_bindings": overlap.MaterialBindings,
	})
	require.NoError(t, err)
	proposals.ModelReceipts = []ModelReceiptBinding830G3{first, second, overlap}
	require.Empty(t, validModelReceiptRequests830G3(proposals, bundle.Request.ResolutionInputs.Corpus, entries))

	foreignIdentity := second
	foreignPermit := *foreignIdentity.PolicyReceipt.PermitView
	foreignIdentity.PolicyReceipt.PermitView = &foreignPermit
	foreignIdentity.PolicyReceipt.AdmissionHash = first.PolicyReceipt.AdmissionHash
	foreignIdentity.PolicyReceipt.RunID = first.PolicyReceipt.RunID
	foreignIdentity.PolicyReceipt.RunRevision = first.PolicyReceipt.RunRevision
	foreignIdentity.PolicyReceipt.IdentityKey = append([]string(nil), first.PolicyReceipt.IdentityKey...)
	foreignIdentity.PolicyReceipt.IdentityKey[0] = "foreign-provider"
	foreignIdentity.PolicyReceipt.PermitView.Identity.Provider = "foreign-provider"
	foreignIdentity.PolicyReceipt.PermitView.AdmissionHash = first.PolicyReceipt.AdmissionHash
	foreignDigest, err := permitDigest830G3(*foreignIdentity.PolicyReceipt.PermitView)
	require.NoError(t, err)
	foreignIdentity.PolicyReceipt.PermitDigest = &foreignDigest
	require.NoError(t, validatePolicyReceipt830G3(foreignIdentity.PolicyReceipt))
	proposals.ModelReceipts = []ModelReceiptBinding830G3{first, foreignIdentity, third}
	require.Empty(t, validModelReceiptRequests830G3(proposals, bundle.Request.ResolutionInputs.Corpus, entries))
}

func TestSingleOriginPartialReceiptKeepsFullCorpusBinding830G3(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &bundle))
	typed, err := decodeResolutionInputs830G3(bundle.Request.ResolutionInputs, bundle.Request.Resolution)
	require.NoError(t, err)
	receipt := typed.Proposals.ModelReceipts[0]
	receipt.MaterialBindings = append([]MaterialBinding830G3(nil), receipt.MaterialBindings[:2]...)
	receipt.InputSHA256, err = batchConceptHash830G3("batch-classifier-input.830.g3.v1", map[string]any{
		"corpus_sha256":     bundle.Request.ResolutionInputs.Corpus.CorpusSHA256,
		"material_bindings": receipt.MaterialBindings,
	})
	require.NoError(t, err)
	proposals := typed.Proposals
	proposals.ModelReceipts = []ModelReceiptBinding830G3{receipt}
	entries, _, err := corpusIndexes830G3(bundle.Request.ResolutionInputs.Corpus)
	require.NoError(t, err)
	valid := validModelReceiptRequests830G3(proposals, bundle.Request.ResolutionInputs.Corpus, entries)
	require.True(t, valid[receipt.RequestSHA256])
}
