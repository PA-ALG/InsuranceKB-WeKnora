package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"regexp"
	"strconv"

	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	werrors "github.com/Tencent/WeKnora/internal/errors"
	"github.com/Tencent/WeKnora/internal/logger"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

// G3FirstParseStore keeps the first-parse captures of enterprise Space PDFs (internal/enterprise/capture).
// It never calls a parser. Each call opens the captures under root with keys, so a test may point
// root elsewhere.
type G3FirstParseStore struct {
	root string
	keys *capture.Keys
}

// NewG3FirstParseStore keeps captures in the deployment's capture directory, sealed with keys from
// the citation token signing ring.
func NewG3FirstParseStore(keys *capture.Keys) *G3FirstParseStore {
	return &G3FirstParseStore{root: capture.DefaultRoot(), keys: keys}
}

func (s *G3FirstParseStore) captures() *capture.Store { return capture.NewStore(s.root, s.keys) }

// ReadSourceArtifact reads an exact historical capture. The caller must resolve
// an authorized Space/RAW scope; this method independently checks Knowledge's
// tenant and RAW ownership before opening any signed artifact. It never parses.
func (s *G3FirstParseStore) ReadSourceArtifact(
	ctx context.Context, repo interfaces.KnowledgeRepository, scope types.WikiReleaseScope,
	knowledgeID string, attempt int64,
) (*source.Artifact, error) {
	var store *capture.Store
	if s != nil {
		store = s.captures()
	}
	reader, _ := repo.(capture.KnowledgeReader)
	return capture.ReadSourceArtifact(ctx, store, reader, scope, knowledgeID, attempt)
}

// save seals the first parse of one exact source revision.
func (s *G3FirstParseStore) save(id capture.Identity, result *types.ReadResult, chunks []types.ParsedChunk) error {
	if s == nil {
		return capture.ErrUnavailable
	}
	return s.captures().Save(id, result, chunks, nil)
}

// note records why one exact source revision was not captured (S11f).
func (s *G3FirstParseStore) note(id capture.Identity, reason string, page int) error {
	if s == nil {
		return capture.ErrUnavailable
	}
	return s.captures().SaveNote(id, reason, page)
}

// scannedPage is docreader's capture refusal for the first page without a text layer; the same
// message enterpriseScannedPDF matches, with the page number captured.
var scannedPage = regexp.MustCompile(`^page ([1-9][0-9]*) is scanned$`)

// noteScannedPDF ends the docreader stage of an enterprise scanned PDF exactly as S4c-2c defined and
// notes the first scanned page, so the page API can say why the revision has no capture. data are
// the bytes this parse read: the note is signed only for the revision they are. The note is only an
// explanation: failing to write it changes nothing about the parse.
func (s *knowledgeService) noteScannedPDF(
	ctx context.Context, k *types.Knowledge, p types.DocumentProcessPayload, parserError string, data []byte,
) {
	s.endStage(ctx, k.ID, types.StageDocReader, types.JSONMap{
		"first_parse_saved": false, "not_captured_reason": "scanned_page",
	})
	if !boundToBytes(k, p, data) {
		logger.Warnf(ctx, "[capture note] not saved knowledge=%s reason=REVISION_BINDING", k.ID)
		return
	}
	match := scannedPage.FindStringSubmatch(parserError)
	if match == nil {
		return // enterpriseScannedPDF matched the same pattern; unreachable
	}
	page, err := strconv.Atoi(match[1])
	if err != nil || s.firstParse.note(revisionIdentity(k, p), source.NotCapturedScannedPage, page) != nil {
		logger.Warnf(ctx, "[capture note] not saved knowledge=%s reason=NOTE_UNAVAILABLE", k.ID)
	}
}

// boundToBytes is the binding a capture or note is saved under: the payload names the knowledge's
// current parse attempt, and the bytes this parse read are that revision's file.
func boundToBytes(k *types.Knowledge, p types.DocumentProcessPayload, data []byte) bool {
	if p.Revision == nil || p.Revision.ParseAttempt != k.CurrentParseAttempt ||
		(p.ParseAttempt > 0 && p.Revision.ParseAttempt != p.ParseAttempt) {
		return false
	}
	sum := sha256.Sum256(data)
	return p.Revision.FileSHA256 == hex.EncodeToString(sum[:])
}

func revisionIdentity(k *types.Knowledge, p types.DocumentProcessPayload) capture.Identity {
	return capture.Identity{
		TenantID: k.TenantID, RawKBID: k.KnowledgeBaseID, KnowledgeID: k.ID,
		ParseAttempt: p.Revision.ParseAttempt, SourceSHA256: p.Revision.FileSHA256,
	}
}

func (s *knowledgeService) failG3FirstParse(ctx context.Context, knowledge *types.Knowledge, cause error) error {
	s.failStage(ctx, knowledge.ID, types.StageDocReader, werrors.ErrCodeDocReaderParseFailed,
		"G3 first parse artifact unavailable", cause)
	_, err := s.failKnowledge(ctx, knowledge, true, "G3_FIRST_PARSE_ARTIFACT_UNAVAILABLE: %v", cause)
	return err
}

// captureOffice seals the Office structure of one parse of an enterprise RAW upload, next to the
// upstream parse of the same bytes (S11b). The parse itself is never changed: when the structure
// cannot be extracted or sealed, the knowledge is processed as usual and its source pages report the
// revision as not captured. Only the typed code is logged, never document text.
func (s *knowledgeService) captureOffice(
	ctx context.Context, k *types.Knowledge, p types.DocumentProcessPayload, fileType string, data []byte,
) {
	if k == nil || p.URL != "" || p.FileURL != "" || !ooxml.Supports(fileType) ||
		s.captureScope == nil || !s.captureScope.RawKB(k.TenantID, k.KnowledgeBaseID) {
		return
	}
	if !boundToBytes(k, p, data) {
		logger.Warnf(ctx, "[office capture] not saved knowledge=%s reason=REVISION_BINDING", k.ID)
		return
	}
	id := revisionIdentity(k, p)
	result, chunks, err := capture.Office(fileType, data)
	if err == nil {
		err = s.firstParse.save(id, result, chunks)
	}
	if err != nil {
		reason := "CAPTURE_UNAVAILABLE"
		var failure *ooxml.Error
		if errors.As(err, &failure) {
			reason = failure.Code
		}
		logger.Warnf(ctx, "[office capture] not saved knowledge=%s reason=%s", k.ID, reason)
		if s.firstParse.note(id, source.NotCapturedOfficeUnreadable, 0) != nil {
			logger.Warnf(ctx, "[capture note] not saved knowledge=%s reason=NOTE_UNAVAILABLE", k.ID)
		}
	}
}
