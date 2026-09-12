package service

import (
	"encoding/json"
	"github.com/Tencent/WeKnora/internal/types"
	"os"
	"path/filepath"
)

const publishedBatchReuseDomain830G3 = "weknora.published-batch-validation.830.g3.v1"

// This is a signed memo of the existing semantic publication check, never a
// second release authority. Every read still opens the current scoped release
// and checks its immutable members and the caller's current access.
type publishedBatchReadReuse830G3 struct {
	root  string
	codec *SchemaWikiCitationTokenCodec
}

func newPublishedBatchReadReuse830G3(codec *SchemaWikiCitationTokenCodec) *publishedBatchReadReuse830G3 {
	root := os.Getenv("LOCAL_STORAGE_BASE_DIR")
	if root == "" {
		root = "/data/files"
	}
	return &publishedBatchReadReuse830G3{root: filepath.Join(root, ".concept-published-read-v1"), codec: codec}
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

// Called only after full validation at an explicit preparation/activation gate.
func (s *publishedBatchReadReuse830G3) rememberValidated(p *types.WikiReleasePreparation, scope types.WikiReleaseScope) error {
	if s == nil {
		return ErrSchemaWikiPreparationInvalid
	}
	key, err := publishedBatchInputKey830G3(p, scope)
	if err != nil {
		return err
	}
	payload, err := json.Marshal(p.CandidateDigest)
	if err != nil {
		return err
	}
	encoded, err := sealConceptDerivedArtifact830G3(s.codec, publishedBatchReuseDomain830G3, key, payload)
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
	return os.Rename(f.Name(), filepath.Join(s.root, key+".json"))
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
	encoded, err := os.ReadFile(filepath.Join(s.root, key+".json"))
	if err != nil {
		return bundle, nil, ErrSchemaWikiPreparationInvalid
	}
	payload, err := openConceptDerivedArtifact830G3(s.codec, publishedBatchReuseDomain830G3, key, encoded)
	var candidate string
	if err != nil || json.Unmarshal(payload, &candidate) != nil || candidate != p.CandidateDigest {
		return bundle, nil, ErrSchemaWikiPreparationInvalid
	}
	// The signature binds the exact stored input and existing full validation.
	// Ordinary decoding does not compile or regenerate any member snapshots.
	if json.Unmarshal(p.Manifest, &bundle) != nil || bundle.CandidateHash != p.CandidateDigest || batchConceptScope830G3(bundle) != scope {
		return bundle, nil, ErrSchemaWikiPreparationInvalid
	}
	return bundle, p.Members, nil
}

func (s *WikiReleaseService) validatePublishedBatchConceptPreparation830G3(p *types.WikiReleasePreparation, scope types.WikiReleaseScope) (types.BatchConceptCandidateBundle830G3, []types.WikiReleaseMemberSnapshot, error) {
	return s.publishedBatchReuse830G3().read(p, scope)
}
