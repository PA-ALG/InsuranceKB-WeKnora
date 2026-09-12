package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/gob"
	"encoding/json"
	"os"
	"path/filepath"
	"sync"

	"github.com/Tencent/WeKnora/internal/types"
)

const publishedBatchReuseDomain830G3 = "weknora.published-batch-read-projection.830.g3.v2"
const publishedBatchReadProjectionContract830G3 = "published-batch-read-projection.830.g3.v2"
const publishedBatchLegacyReuseDomain830G3 = "weknora.published-batch-validation.830.g3.v1"

// publishedBatchReadProjection830G3 is derived once from a fully validated
// preparation. It retains only values used by published GETs and is signed by
// the existing citation key ring; it never acts as a release or source head.
type publishedBatchReadProjection830G3 struct {
	Contract      string                                 `json:"contract"`
	InputKey      string                                 `json:"input_key"`
	Bundle        types.BatchConceptCandidateBundle830G3 `json:"bundle"`
	MemberDigests map[string]string                      `json:"member_digests"`
}

type publishedBatchReadCache830G3 struct {
	projection publishedBatchReadProjection830G3
	members    []types.WikiReleaseMemberSnapshot
}

func (s *publishedBatchReadReuse830G3) artifactPath(p *types.WikiReleasePreparation, scope types.WikiReleaseScope) (string, error) {
	if s == nil {
		return "", ErrSchemaWikiPreparationInvalid
	}
	key, err := publishedBatchInputKey830G3(p, scope)
	if err != nil {
		return "", err
	}
	return filepath.Join(s.root, key+".json"), nil
}

// loadPublishedBatchReadProjection830G3 fetches only stored authorization
// identities, then opens the signed prepare-time projection. found=false means
// an older or non-G3 preparation and lets the caller use its existing path.
func (s *WikiReleaseService) loadPublishedBatchReadProjection830G3(
	ctx context.Context, scope types.WikiReleaseScope, preparationID string,
) (*types.WikiReleasePreparation, types.BatchConceptCandidateBundle830G3, []types.WikiReleaseMemberSnapshot, bool, error) {
	var empty types.BatchConceptCandidateBundle830G3
	if s == nil || s.repository == nil {
		return nil, empty, nil, false, ErrSchemaWikiPreparationInvalid
	}
	preparation, err := s.repository.GetReadyPreparationMetadata(ctx, scope, preparationID)
	if err != nil {
		return nil, empty, nil, false, err
	}
	store := s.publishedBatchReuse830G3()
	if store == nil {
		return preparation, empty, nil, false, nil
	}
	path, keyErr := store.artifactPath(preparation, scope)
	if keyErr != nil {
		return nil, empty, nil, false, keyErr
	}
	if _, statErr := os.Stat(path); os.IsNotExist(statErr) {
		return preparation, empty, nil, false, nil
	} else if statErr != nil {
		return nil, empty, nil, true, ErrSchemaWikiPreparationInvalid
	}
	bundle, members, err := store.read(preparation, scope)
	if err != nil {
		return nil, empty, nil, true, err
	}
	return preparation, bundle, members, true, nil
}

type publishedBatchReadProjectionSeal830G3 struct {
	KeyID     string `json:"key_id"`
	Key       string `json:"key"`
	Payload   []byte `json:"payload"`
	Signature []byte `json:"signature"`
}

func sealPublishedBatchReadProjection830G3(codec *SchemaWikiCitationTokenCodec, key string, payload []byte) ([]byte, error) {
	if codec == nil || key == "" {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	private := codec.privateKeys[codec.activeKeyID]
	if len(private) != ed25519.PrivateKeySize {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	seal := publishedBatchReadProjectionSeal830G3{
		KeyID: codec.activeKeyID, Key: key, Payload: payload,
		Signature: ed25519.Sign(private, conceptSourceReuseSignedBytes830G3(
			publishedBatchReuseDomain830G3, key, payload,
		)),
	}
	return json.Marshal(seal)
}

func openPublishedBatchReadProjection830G3(codec *SchemaWikiCitationTokenCodec, key string, encoded []byte) ([]byte, error) {
	var seal publishedBatchReadProjectionSeal830G3
	if codec == nil || key == "" || json.Unmarshal(encoded, &seal) != nil || seal.Key != key {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	public := codec.publicKeys[seal.KeyID]
	if len(public) != ed25519.PublicKeySize || !ed25519.Verify(public,
		conceptSourceReuseSignedBytes830G3(publishedBatchReuseDomain830G3, key, seal.Payload), seal.Signature) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	return seal.Payload, nil
}

// This is a signed memo of the existing semantic publication check, never a
// second release authority. Every read still opens the current scoped release
// and checks its immutable members and the caller's current access.
type publishedBatchReadReuse830G3 struct {
	root    string
	codec   *SchemaWikiCitationTokenCodec
	mu      sync.RWMutex
	entries map[string]publishedBatchReadCache830G3
}

func newPublishedBatchReadReuse830G3(codec *SchemaWikiCitationTokenCodec) *publishedBatchReadReuse830G3 {
	root := os.Getenv("LOCAL_STORAGE_BASE_DIR")
	if root == "" {
		root = "/data/files"
	}
	return &publishedBatchReadReuse830G3{
		root: filepath.Join(root, ".concept-published-read-v2"), codec: codec,
		entries: map[string]publishedBatchReadCache830G3{},
	}
}

func (s *WikiReleaseService) publishedBatchReuse830G3() *publishedBatchReadReuse830G3 {
	if s == nil {
		return nil
	}
	if s.publishedReadReuse != nil {
		return s.publishedReadReuse
	}
	authority, ok := s.conceptSourceAuthorityVerifier830G2.(*ConceptSourceAuthorityService830G2)
	if !ok || authority == nil {
		return nil
	}
	return newPublishedBatchReadReuse830G3(authority.codec)
}

func publishedBatchInputKey830G3(p *types.WikiReleasePreparation, scope types.WikiReleaseScope) (string, error) {
	if p == nil || p.WikiReleaseScope != scope || !validBatchConceptPreparationID830G3(p.ID) ||
		p.Status != types.WikiReleasePreparationReady || p.ReviewDecisionDigest == "" ||
		digestWikiReleasePreparation(p) != p.PreparationDigest {
		return "", ErrSchemaWikiPreparationInvalid
	}
	raw, err := json.Marshal(struct {
		Preparation string `json:"preparation"`
		Manifest    string `json:"manifest"`
		Candidate   string `json:"candidate"`
	}{
		Preparation: p.PreparationDigest,
		Manifest:    p.ManifestDigest,
		Candidate:   p.CandidateDigest,
	})
	if err != nil {
		return "", ErrSchemaWikiPreparationInvalid
	}
	return digestWikiReleaseBytes(raw), nil
}

func publishedBatchLegacyInputKey830G3(p *types.WikiReleasePreparation, scope types.WikiReleaseScope) (string, error) {
	if p == nil || p.WikiReleaseScope != scope || !validBatchConceptPreparationID830G3(p.ID) ||
		p.Status != types.WikiReleasePreparationReady || p.ReviewDecisionDigest == "" ||
		digestWikiReleasePreparation(p) != p.PreparationDigest {
		return "", ErrSchemaWikiPreparationInvalid
	}
	rows, err := json.Marshal(p.Members)
	if err != nil {
		return "", ErrSchemaWikiPreparationInvalid
	}
	raw, err := json.Marshal(struct{ Preparation, Manifest, Members string }{
		p.PreparationDigest, digestWikiReleaseBytes(p.Manifest), digestWikiReleaseBytes(rows),
	})
	if err != nil {
		return "", ErrSchemaWikiPreparationInvalid
	}
	return digestWikiReleaseBytes(raw), nil
}

func publishedBatchProjectedBundle830G3(bundle types.BatchConceptCandidateBundle830G3) types.BatchConceptCandidateBundle830G3 {
	base := bundle.Request.BaseRequest
	base = types.ConceptCompileRequest830G2{
		TenantID: base.TenantID, SpaceID: base.SpaceID,
		RawKBID: base.RawKBID, WikiKBID: base.WikiKBID,
		Sources: base.Sources, BaseReleaseID: base.BaseReleaseID,
		BaseActivationEpoch: base.BaseActivationEpoch,
	}
	catalog := bundle.Request.Catalog
	return types.BatchConceptCandidateBundle830G3{
		Contract:              bundle.Contract,
		NavigationAssignments: bundle.NavigationAssignments,
		Request: types.BatchConceptCompileRequest830G3{
			BaseRequest: base,
			Catalog: types.SchemaPackCatalog830G3{
				CatalogID: catalog.CatalogID, CatalogVersion: catalog.CatalogVersion,
				CatalogSHA256: catalog.CatalogSHA256,
			},
			EntityBindings: bundle.Request.EntityBindings,
		},
		CompileResult: types.ConceptCompileResult830G2{Output: types.ConceptCompileOutput830G2{
			Definitions: bundle.CompileResult.Output.Definitions,
			Fields:      bundle.CompileResult.Output.Fields,
			Pages:       bundle.CompileResult.Output.Pages,
		}},
		PageManifest:  types.BatchConceptPageManifest830G3{Members: bundle.PageManifest.Members},
		CandidateHash: bundle.CandidateHash,
	}
}

func (p publishedBatchReadProjection830G3) expectedMembers() ([]types.WikiReleaseMemberSnapshot, error) {
	if p.Contract != publishedBatchReadProjectionContract830G3 || p.InputKey == "" ||
		len(p.Bundle.PageManifest.Members) != len(p.MemberDigests) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	result := make([]types.WikiReleaseMemberSnapshot, 0, len(p.Bundle.PageManifest.Members))
	for _, member := range p.Bundle.PageManifest.Members {
		digest, ok := p.MemberDigests[member.MemberID]
		if !ok || digest == "" {
			return nil, ErrSchemaWikiPreparationInvalid
		}
		result = append(result, types.WikiReleaseMemberSnapshot{
			Kind: member.Kind, LogicalSlug: member.MemberID,
			RevisionID: p.Bundle.CandidateHash, MemberDigest: digest,
			Title: member.Title, Content: member.Content,
			Payload: append(json.RawMessage(nil), member.Payload...),
		})
	}
	return result, nil
}

// publishedBatchMemberIdentitiesEqual830G3 checks the current release rows
// against identities frozen by the signed projection. Published content is
// then returned from that projection rather than from mutable row payloads.
func publishedBatchMemberIdentitiesEqual830G3(
	expected []types.WikiReleaseMemberSnapshot,
	stored []types.WikiReleaseMemberSnapshot,
) bool {
	if len(expected) != len(stored) {
		return false
	}
	bySlug := make(map[string]types.WikiReleaseMemberSnapshot, len(stored))
	for _, member := range stored {
		if member.LogicalSlug == "" {
			return false
		}
		if _, duplicate := bySlug[member.LogicalSlug]; duplicate {
			return false
		}
		bySlug[member.LogicalSlug] = member
	}
	for _, member := range expected {
		storedMember, ok := bySlug[member.LogicalSlug]
		if !ok || storedMember.Kind != member.Kind ||
			storedMember.RevisionID != member.RevisionID ||
			storedMember.MemberDigest != member.MemberDigest {
			return false
		}
		delete(bySlug, member.LogicalSlug)
	}
	return len(bySlug) == 0
}

// Called only after full validation at an explicit preparation/activation gate.
func (s *publishedBatchReadReuse830G3) rememberValidated(p *types.WikiReleasePreparation, scope types.WikiReleaseScope) error {
	if s == nil {
		return ErrSchemaWikiPreparationInvalid
	}
	key, err := publishedBatchInputKey830G3(p, scope)
	if err != nil {
		return err
	}
	var bundle types.BatchConceptCandidateBundle830G3
	if len(p.Manifest) == 0 || json.Unmarshal(p.Manifest, &bundle) != nil || bundle.CandidateHash != p.CandidateDigest ||
		batchConceptScope830G3(bundle) != scope {
		return ErrSchemaWikiPreparationInvalid
	}
	memberDigests := make(map[string]string, len(p.Members))
	for _, member := range p.Members {
		if member.LogicalSlug == "" || member.MemberDigest == "" {
			return ErrSchemaWikiPreparationInvalid
		}
		if _, duplicate := memberDigests[member.LogicalSlug]; duplicate {
			return ErrSchemaWikiPreparationInvalid
		}
		memberDigests[member.LogicalSlug] = member.MemberDigest
	}
	projection := publishedBatchReadProjection830G3{
		Contract: publishedBatchReadProjectionContract830G3,
		InputKey: key, Bundle: publishedBatchProjectedBundle830G3(bundle),
		MemberDigests: memberDigests,
	}
	expected, err := projection.expectedMembers()
	if err != nil || !publishedBatchMemberIdentitiesEqual830G3(expected, p.Members) {
		return ErrSchemaWikiPreparationInvalid
	}
	var payload bytes.Buffer
	if err = gob.NewEncoder(&payload).Encode(projection); err != nil {
		return err
	}
	encoded, err := sealPublishedBatchReadProjection830G3(s.codec, key, payload.Bytes())
	if err != nil {
		return err
	}
	if err = os.MkdirAll(s.root, 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(s.root, ".prepare-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(encoded); err != nil {
		f.Close()
		return err
	}
	if err = f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if err = os.Rename(f.Name(), filepath.Join(s.root, key+".json")); err != nil {
		return err
	}
	s.mu.Lock()
	s.entries[key] = publishedBatchReadCache830G3{projection: projection, members: expected}
	s.mu.Unlock()
	return nil
}

func (s *publishedBatchReadReuse830G3) read(p *types.WikiReleasePreparation, scope types.WikiReleaseScope) (types.BatchConceptCandidateBundle830G3, []types.WikiReleaseMemberSnapshot, error) {
	var bundle types.BatchConceptCandidateBundle830G3
	if s == nil {
		return bundle, nil, ErrSchemaWikiPreparationInvalid
	}
	key, err := publishedBatchInputKey830G3(p, scope)
	if err != nil {
		return bundle, nil, err
	}
	s.mu.RLock()
	entry, cached := s.entries[key]
	s.mu.RUnlock()
	projection := entry.projection
	expected := entry.members
	if !cached {
		encoded, readErr := os.ReadFile(filepath.Join(s.root, key+".json"))
		if readErr != nil {
			return bundle, nil, ErrSchemaWikiPreparationInvalid
		}
		payload, openErr := openPublishedBatchReadProjection830G3(s.codec, key, encoded)
		if openErr != nil || gob.NewDecoder(bytes.NewReader(payload)).Decode(&projection) != nil {
			return bundle, nil, ErrSchemaWikiPreparationInvalid
		}
		expected, err = projection.expectedMembers()
		if err != nil {
			return bundle, nil, err
		}
		s.mu.Lock()
		s.entries[key] = publishedBatchReadCache830G3{projection: projection, members: expected}
		s.mu.Unlock()
	}
	if projection.Contract != publishedBatchReadProjectionContract830G3 || projection.InputKey != key ||
		projection.Bundle.CandidateHash != p.CandidateDigest ||
		batchConceptScope830G3(projection.Bundle) != scope {
		return bundle, nil, ErrSchemaWikiPreparationInvalid
	}
	// Full values are optional on published reads. If a caller already loaded
	// them (activation or explicit preparation), still reject any drift.
	if len(p.Manifest) != 0 && digestWikiReleaseBytes(p.Manifest) != p.ManifestDigest {
		return bundle, nil, ErrSchemaWikiPreparationInvalid
	}
	if p.Members != nil && !conceptMemberSnapshotSetsEqual830G2(expected, p.Members) {
		return bundle, nil, ErrSchemaWikiPreparationInvalid
	}
	return projection.Bundle, expected, nil
}

func (s *publishedBatchReadReuse830G3) readLegacy(p *types.WikiReleasePreparation, scope types.WikiReleaseScope) (types.BatchConceptCandidateBundle830G3, []types.WikiReleaseMemberSnapshot, error) {
	var bundle types.BatchConceptCandidateBundle830G3
	if s == nil {
		return bundle, nil, ErrSchemaWikiPreparationInvalid
	}
	key, err := publishedBatchLegacyInputKey830G3(p, scope)
	if err != nil {
		return bundle, nil, err
	}
	legacyRoot := filepath.Join(filepath.Dir(s.root), ".concept-published-read-v1")
	encoded, err := os.ReadFile(filepath.Join(legacyRoot, key+".json"))
	if err != nil {
		return bundle, nil, ErrSchemaWikiPreparationInvalid
	}
	payload, err := openConceptDerivedArtifact830G3(s.codec, publishedBatchLegacyReuseDomain830G3, key, encoded)
	var candidate string
	if err != nil || json.Unmarshal(payload, &candidate) != nil || candidate != p.CandidateDigest ||
		json.Unmarshal(p.Manifest, &bundle) != nil || bundle.CandidateHash != p.CandidateDigest ||
		batchConceptScope830G3(bundle) != scope {
		return bundle, nil, ErrSchemaWikiPreparationInvalid
	}
	return bundle, p.Members, nil
}

func (s *WikiReleaseService) validatePublishedBatchConceptPreparation830G3(p *types.WikiReleasePreparation, scope types.WikiReleaseScope) (types.BatchConceptCandidateBundle830G3, []types.WikiReleaseMemberSnapshot, error) {
	store := s.publishedBatchReuse830G3()
	if path, err := store.artifactPath(p, scope); err == nil {
		if _, statErr := os.Stat(path); statErr == nil {
			return store.read(p, scope)
		}
	}
	return store.readLegacy(p, scope)
}
