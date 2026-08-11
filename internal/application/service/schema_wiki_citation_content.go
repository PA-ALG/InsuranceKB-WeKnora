package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"strings"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

const schemaWikiCitationTokenTTL = 5 * time.Minute

type schemaWikiCitationTokenClaimsV1 struct {
	Contract      string                                     `json:"contract"`
	TokenKeyID    string                                     `json:"token_key_id"`
	IssuedAtUnix  int64                                      `json:"issued_at_unix"`
	ExpiresAtUnix int64                                      `json:"expires_at_unix"`
	Scope         types.WikiReleaseScope                     `json:"scope"`
	Authority     types.SchemaWikiCitationContentAuthorityV1 `json:"authority"`
}

// SchemaWikiCitationTokenCodec signs the hash-only public authority and scope
// using the deployment-owned third signing domain. No review/publish key is
// accepted, and no quote snapshot is placed in the token.
type SchemaWikiCitationTokenCodec struct {
	activeKeyID string
	privateKeys map[string]ed25519.PrivateKey
	publicKeys  map[string]ed25519.PublicKey
	now         func() time.Time
}

func NewSchemaWikiCitationTokenCodec(
	activeKeyID string,
	privateKeys map[string]ed25519.PrivateKey,
	now func() time.Time,
) (*SchemaWikiCitationTokenCodec, error) {
	if now == nil {
		now = time.Now
	}
	codec := &SchemaWikiCitationTokenCodec{
		activeKeyID: activeKeyID,
		privateKeys: map[string]ed25519.PrivateKey{},
		publicKeys:  map[string]ed25519.PublicKey{},
		now:         now,
	}
	if activeKeyID == "" && len(privateKeys) == 0 {
		return codec, nil
	}
	if activeKeyID == "" || len(privateKeys) == 0 {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	seenMaterial := map[string]struct{}{}
	for keyID, privateKey := range privateKeys {
		if keyID == "" || strings.TrimSpace(keyID) != keyID ||
			len(privateKey) != ed25519.PrivateKeySize {
			return nil, ErrSchemaWikiCitationUnavailable
		}
		publicKey, ok := privateKey.Public().(ed25519.PublicKey)
		if !ok {
			return nil, ErrSchemaWikiCitationUnavailable
		}
		if _, duplicate := seenMaterial[string(publicKey)]; duplicate {
			return nil, ErrSchemaWikiCitationUnavailable
		}
		seenMaterial[string(publicKey)] = struct{}{}
		codec.privateKeys[keyID] = append(ed25519.PrivateKey(nil), privateKey...)
		codec.publicKeys[keyID] = append(ed25519.PublicKey(nil), publicKey...)
	}
	if _, exists := codec.privateKeys[activeKeyID]; !exists {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	return codec, nil
}

func (c *SchemaWikiCitationTokenCodec) issue(
	claims schemaWikiCitationTokenClaimsV1,
) (string, error) {
	if c == nil || c.activeKeyID == "" || claims.TokenKeyID != c.activeKeyID {
		return "", ErrSchemaWikiCitationUnavailable
	}
	privateKey, ok := c.privateKeys[c.activeKeyID]
	if !ok {
		return "", ErrSchemaWikiCitationUnavailable
	}
	payload, err := json.Marshal(claims)
	if err != nil {
		return "", ErrSchemaWikiCitationUnavailable
	}
	signed := append([]byte("schema-wiki-citation-content-token.v1\n"), payload...)
	signature := ed25519.Sign(privateKey, signed)
	return strings.Join([]string{
		base64.RawURLEncoding.EncodeToString([]byte(c.activeKeyID)),
		base64.RawURLEncoding.EncodeToString(payload),
		base64.RawURLEncoding.EncodeToString(signature),
	}, "."), nil
}

func (c *SchemaWikiCitationTokenCodec) verify(
	token string,
) (schemaWikiCitationTokenClaimsV1, error) {
	empty := schemaWikiCitationTokenClaimsV1{}
	parts := strings.Split(token, ".")
	if c == nil || len(parts) != 3 || token != strings.TrimSpace(token) {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	keyIDBytes, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil || base64.RawURLEncoding.EncodeToString(keyIDBytes) != parts[0] {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	keyID := string(keyIDBytes)
	publicKey, ok := c.publicKeys[keyID]
	if !ok {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil || base64.RawURLEncoding.EncodeToString(payload) != parts[1] {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil || len(signature) != ed25519.SignatureSize ||
		base64.RawURLEncoding.EncodeToString(signature) != parts[2] {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	signed := append([]byte("schema-wiki-citation-content-token.v1\n"), payload...)
	if !ed25519.Verify(publicKey, signed, signature) {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var claims schemaWikiCitationTokenClaimsV1
	if err := decoder.Decode(&claims); err != nil || !schemaWikiCitationJSONEOF(decoder) {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	canonical, err := json.Marshal(claims)
	if err != nil || !bytes.Equal(payload, canonical) ||
		claims.Contract != "schema-wiki-citation-content-token-claims.v1" ||
		claims.TokenKeyID != keyID || claims.Authority.TokenKeyID != keyID ||
		claims.Authority.OpaqueToken != "" ||
		claims.IssuedAtUnix <= 0 || claims.ExpiresAtUnix <= claims.IssuedAtUnix ||
		claims.ExpiresAtUnix-claims.IssuedAtUnix != int64(schemaWikiCitationTokenTTL/time.Second) ||
		c.now().UTC().Unix() < claims.IssuedAtUnix || c.now().UTC().Unix() >= claims.ExpiresAtUnix ||
		types.ValidateSchemaWikiCitationContentAuthorityV1(claims.Authority) != nil {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	return claims, nil
}

func schemaWikiCitationJSONEOF(decoder *json.Decoder) bool {
	var trailing any
	return decoder.Decode(&trailing) == io.EOF
}

type schemaWikiRevisionBlobReader interface {
	ReadExactRevisionSource(context.Context, types.LiveRevisionSourceReceiptV1) ([]byte, error)
}

type schemaWikiRevisionSourceBlobReader struct {
	revisions schemaWikiCitationRevisionRepository
	files     interfaces.FileService
}

// NewSchemaWikiRevisionBlobReader opens only the resource pinned by the exact
// revision source receipt. It never asks the current-file or presigned URL
// endpoint for content.
func NewSchemaWikiRevisionBlobReader(
	knowledgeRepository interfaces.KnowledgeRepository,
	files interfaces.FileService,
) schemaWikiRevisionBlobReader {
	revisions, _ := knowledgeRepository.(schemaWikiCitationRevisionRepository)
	return &schemaWikiRevisionSourceBlobReader{revisions: revisions, files: files}
}

func (r *schemaWikiRevisionSourceBlobReader) ReadExactRevisionSource(
	ctx context.Context,
	receipt types.LiveRevisionSourceReceiptV1,
) ([]byte, error) {
	if r == nil || r.revisions == nil || r.files == nil ||
		types.ValidateLiveRevisionSourceReceiptV1(receipt) != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	tenantID, ok := ctx.Value(types.TenantIDContextKey).(uint64)
	if !ok || tenantID == 0 || tenantID != receipt.TenantID {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	source, resource, err := r.revisions.GetRevisionSource(
		ctx, tenantID, receipt.KnowledgeID, receipt.WeKnoraParseAttempt,
	)
	if err != nil || source == nil || resource == nil ||
		source.RevisionSourceID != receipt.RevisionSourceID ||
		source.ResourceID != receipt.ResourceID || source.FileSHA256 != receipt.FileSHA256 ||
		source.Size != receipt.Size || source.MimeType != receipt.MimeType ||
		source.RetentionState != types.KnowledgeRevisionSourcePinned || source.PageCount == nil ||
		*source.PageCount != receipt.PageCount || resource.ID != receipt.ResourceID ||
		resource.TenantID != receipt.TenantID || resource.ContentHash != receipt.FileSHA256 ||
		resource.Size != receipt.Size || resource.MimeType != receipt.MimeType ||
		resource.State != types.ResourceStateActive ||
		resource.Lifecycle != types.ResourceLifecyclePersistent {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	opened, err := r.files.GetFile(ctx, types.BuildResourcePath(resource.Handle))
	if err != nil || opened == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	data, readErr := io.ReadAll(io.LimitReader(opened, receipt.Size+1))
	closeErr := opened.Close()
	sum := sha256.Sum256(data)
	if readErr != nil || closeErr != nil || int64(len(data)) != receipt.Size ||
		hex.EncodeToString(sum[:]) != receipt.FileSHA256 {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	return data, nil
}

type schemaWikiCitationContentService struct {
	adapter *schemaWikiCitationRevisionReadAdapter
	blob    schemaWikiRevisionBlobReader
	codec   *SchemaWikiCitationTokenCodec
}

func newSchemaWikiCitationContentService(
	adapter *schemaWikiCitationRevisionReadAdapter,
	blob schemaWikiRevisionBlobReader,
	codec *SchemaWikiCitationTokenCodec,
) *schemaWikiCitationContentService {
	return &schemaWikiCitationContentService{adapter: adapter, blob: blob, codec: codec}
}

func NewSchemaWikiCitationContentService(
	adapter *schemaWikiCitationRevisionReadAdapter,
	blob schemaWikiRevisionBlobReader,
	codec *SchemaWikiCitationTokenCodec,
) SchemaWikiCitationContentPort {
	return newSchemaWikiCitationContentService(adapter, blob, codec)
}

func (s *schemaWikiCitationContentService) IssueExactRevision(
	ctx context.Context,
	request CitationRevisionReadRequestV1,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	if s == nil || s.adapter == nil || s.codec == nil || s.codec.activeKeyID == "" {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	if request.CoordinateAuthorityReceipt != nil &&
		(request.Citation.PageNumber <= 0 ||
			request.Citation.PageNumber > request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt.PageCount) {
		return nil, ErrSchemaWikiCitationPageUnavailable
	}
	resolved, err := s.adapter.resolveExactRevisionAuthority(ctx, request)
	if err != nil {
		return nil, err
	}
	now := s.codec.now().UTC()
	authority, err := schemaWikiCitationPublicAuthority(
		request, *resolved, s.codec.activeKeyID, now.Add(schemaWikiCitationTokenTTL).Unix(),
	)
	if err != nil {
		return nil, err
	}
	claims := schemaWikiCitationTokenClaimsV1{
		Contract:   "schema-wiki-citation-content-token-claims.v1",
		TokenKeyID: s.codec.activeKeyID, IssuedAtUnix: now.Unix(),
		ExpiresAtUnix: authority.ExpiresAtUnix, Scope: request.Scope,
		Authority: *authority,
	}
	token, err := s.codec.issue(claims)
	if err != nil {
		return nil, err
	}
	authority.OpaqueToken = token
	return authority, nil
}

func (s *schemaWikiCitationContentService) ResolveOpaqueToken(
	_ context.Context,
	scope types.WikiReleaseScope,
	token string,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	if s == nil || s.codec == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	claims, err := s.codec.verify(token)
	if err != nil || claims.Scope != scope {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	authority := claims.Authority
	authority.OpaqueToken = token
	return &authority, nil
}

func (s *schemaWikiCitationContentService) ReadByOpaqueToken(
	ctx context.Context,
	scope types.WikiReleaseScope,
	token string,
	request CitationRevisionReadRequestV1,
) ([]byte, error) {
	if s == nil || s.adapter == nil || s.blob == nil || s.codec == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	claims, err := s.codec.verify(token)
	if err != nil || claims.Scope != scope || request.Scope != scope {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	resolved, err := s.adapter.resolveExactRevisionAuthority(ctx, request)
	if err != nil {
		return nil, err
	}
	expected, err := schemaWikiCitationPublicAuthority(
		request, *resolved, claims.TokenKeyID, claims.ExpiresAtUnix,
	)
	if err != nil || types.ValidateSchemaWikiCitationContentAuthorityAgainst(
		claims.Authority, *expected,
	) != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	opened, err := s.blob.ReadExactRevisionSource(ctx, claims.Authority.RevisionSource)
	if err != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	return opened, nil
}

func schemaWikiCitationPublicAuthority(
	request CitationRevisionReadRequestV1,
	resolved SchemaWikiCitationPreviewAuthorityV1,
	keyID string,
	expiresAtUnix int64,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	if request.CoordinateAuthorityReceipt == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	authority := types.SchemaWikiCitationContentAuthorityV1{
		Contract:   "schema-wiki-citation-content-authority.v1",
		TokenKeyID: keyID, ReleaseID: request.ReleaseID,
		ActivationEpoch: request.ActivationEpoch, CandidateSHA256: request.CandidateSHA256,
		FieldID: request.FieldID, CitationID: request.Citation.CitationID,
		RevisionSource:         request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt,
		CitationSHA256:         request.Citation.CitationSHA256,
		BindingSHA256:          request.Binding.BindingSHA256,
		PageNumber:             request.Citation.PageNumber,
		BBox:                   request.Citation.BBox,
		QuoteSHA256:            request.Citation.QuoteSHA256,
		ContentSnapshotSHA256:  request.Citation.ContentSnapshotSHA256,
		CoordinateSpaceVersion: resolved.CoordinateSpaceVersion,
		PageWidth:              resolved.PageWidth, PageHeight: resolved.PageHeight,
		RotationDegrees: resolved.RotationDegrees,
		RetentionState:  types.KnowledgeRevisionSourcePinned,
		ExpiresAtUnix:   expiresAtUnix,
	}
	digest, err := types.ComputeSchemaWikiCitationContentAuthoritySHA256(authority)
	if err != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	authority.AuthoritySHA256 = digest
	if types.ValidateSchemaWikiCitationContentAuthorityV1(authority) != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	return &authority, nil
}
