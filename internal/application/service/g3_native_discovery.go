package service

// The native producer owns prompts and chunk attribution. Its caller owns
// durable model execution; this service has no model, page-write or release port.
import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"text/template"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/types"
)

const G3NativeDiscoveryRequestContract = "g3-native-discovery-request.830.v1"
const G3NativeDiscoverySnapshotContract = "g3-platform-native-discovery-snapshot.830.v1"
const G3NativeDiscoveryPlanContract = "g3-platform-native-discovery-plan-snapshot.830.v1"

var ErrG3NativeDiscoveryInvalid = errors.New("G3_NATIVE_DISCOVERY_INVALID")

type G3NativeDiscoveryRequest struct {
	Contract             string                          `json:"contract"`
	SourceSnapshotSHA256 string                          `json:"source_snapshot_sha256"`
	Phase                string                          `json:"phase"`
	Language             string                          `json:"language"`
	Granularity          types.WikiExtractionGranularity `json:"granularity"`
	Purpose              string                          `json:"purpose"`
	WindowID             int                             `json:"window_id"`
	DiscoveryRaw         string                          `json:"discovery_raw"`
	CitationRaw          string                          `json:"citation_raw"`
	MaxPromptBytes       int                             `json:"max_prompt_bytes"`
}

type G3NativeDiscoveryWindow struct {
	WindowID     int      `json:"window_id"`
	ChunkIDs     []string `json:"chunk_ids"`
	Prompt       string   `json:"prompt"`
	PromptSHA256 string   `json:"prompt_sha256"`
}

type G3NativeDiscoveryCandidate struct {
	ContentOrigin   string   `json:"content_origin"`
	Kind            string   `json:"kind"`
	Name            string   `json:"name"`
	Slug            string   `json:"slug"`
	Aliases         []string `json:"aliases"`
	Description     string   `json:"description"`
	Details         string   `json:"details"`
	SourceChunks    []string `json:"source_chunks"`
	HasSourceChunks bool     `json:"has_source_chunks"`
}

type G3NativeDiscoverySnapshot struct {
	Contract             string                       `json:"contract"`
	Scope                types.WikiReleaseScope       `json:"scope"`
	KnowledgeID          string                       `json:"knowledge_id"`
	ParseAttempt         int64                        `json:"parse_attempt"`
	SourceSnapshotSHA256 string                       `json:"source_snapshot_sha256"`
	PolicySHA256         string                       `json:"policy_sha256"`
	RequestSHA256        string                       `json:"request_sha256"`
	Phase                string                       `json:"phase"`
	WindowCount          int                          `json:"window_count"`
	Windows              []G3NativeDiscoveryWindow    `json:"windows"`
	Candidates           []G3NativeDiscoveryCandidate `json:"candidates"`
	DiscoveryRawSHA256   string                       `json:"discovery_raw_sha256"`
	CitationRawSHA256    string                       `json:"citation_raw_sha256"`
	SnapshotSHA256       string                       `json:"snapshot_sha256"`
}

type G3SignedNativeDiscoverySnapshot struct {
	Contract  string                        `json:"contract"`
	Snapshot  G3NativeDiscoverySnapshot     `json:"snapshot"`
	Authority G3PlatformSnapshotAuthorityV1 `json:"authority"`
}

type G3NativeDiscoverySourceReader interface {
	Capture(context.Context, types.WikiReleaseScope, string, int64) (*G3PlatformSignedSourceSnapshotV1, error)
}

type G3NativeDiscoveryService struct {
	sources G3NativeDiscoverySourceReader
	signer  G3PlatformSnapshotSigner
}

func NewG3NativeDiscoveryService(sources G3NativeDiscoverySourceReader, signer G3PlatformSnapshotSigner) *G3NativeDiscoveryService {
	return &G3NativeDiscoveryService{sources: sources, signer: signer}
}

func (s *G3NativeDiscoveryService) Process(ctx context.Context, scope types.WikiReleaseScope, knowledgeID string, attempt int64, request G3NativeDiscoveryRequest) (*G3SignedNativeDiscoverySnapshot, error) {
	if s == nil || s.sources == nil || s.signer == nil {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	if request.Contract != G3NativeDiscoveryRequestContract || !validServiceSHA256(request.SourceSnapshotSHA256) ||
		request.MaxPromptBytes <= 0 || request.MaxPromptBytes > 2<<20 ||
		strings.TrimSpace(request.Language) == "" || len(request.Language) > 100 || !request.Granularity.IsValid() || len(request.Purpose) > 16000 ||
		request.WindowID < 0 || len(request.DiscoveryRaw) > 2<<20 || len(request.CitationRaw) > 2<<20 ||
		(request.Phase != "plan" && request.Phase != "cite" && request.Phase != "snapshot") ||
		(request.Phase == "plan" && (request.WindowID != 0 || request.DiscoveryRaw != "" || request.CitationRaw != "")) ||
		(request.Phase == "cite" && request.CitationRaw != "") {
		return nil, ErrG3NativeDiscoveryInvalid
	}
	// Source Capture repeats current ACL and revision custody for every phase,
	// including an attempted replay. A caller-supplied snapshot is never trusted.
	source, err := s.sources.Capture(ctx, scope, knowledgeID, attempt)
	if err != nil {
		return nil, err
	}
	if source == nil || source.Snapshot.Scope != scope || source.Snapshot.Receipt.KnowledgeID != knowledgeID ||
		source.Snapshot.Receipt.ParseAttempt != attempt || source.Snapshot.SnapshotSHA256 != request.SourceSnapshotSHA256 {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	chunks := make([]*types.Chunk, 0, len(source.Snapshot.Chunks))
	for _, chunk := range source.Snapshot.Chunks {
		if chunk.Content == "" {
			continue
		}
		chunks = append(chunks, &types.Chunk{ID: chunk.ID, ChunkIndex: chunk.Index, Content: chunk.Content})
	}
	batches := splitChunksIntoCitationBatches(chunks)
	policy, err := g3PlatformSnapshotDigest("g3-native-discovery-policy.830.v1", map[string]any{
		"language": request.Language, "granularity": request.Granularity, "purpose": request.Purpose,
		"discovery_prompt": agent.WikiCandidateSlugPrompt, "citation_prompt": agent.WikiChunkCitationPrompt,
		"granularity_guidance": agent.WikiGranularityGuidance(string(request.Granularity)),
		"batch_runes":          maxRunesPerCitationBatch,
		"max_prompt_bytes":     request.MaxPromptBytes,
	}, "")
	if err != nil {
		return nil, err
	}
	result := G3NativeDiscoverySnapshot{Contract: G3NativeDiscoverySnapshotContract, Scope: scope,
		KnowledgeID: knowledgeID, ParseAttempt: attempt, SourceSnapshotSHA256: request.SourceSnapshotSHA256,
		PolicySHA256: policy, Phase: request.Phase, WindowCount: len(batches),
		Windows: []G3NativeDiscoveryWindow{}, Candidates: []G3NativeDiscoveryCandidate{},
	}
	result.RequestSHA256, err = g3PlatformSnapshotDigest(request.Contract, request, "")
	if err != nil {
		return nil, err
	}
	if request.Phase != "snapshot" {
		result.Contract = G3NativeDiscoveryPlanContract
	}
	if request.Phase == "plan" {
		for index, batch := range batches {
			window, err := nativeDiscoveryWindow(index, batch, request, nil)
			if err != nil {
				return nil, err
			}
			result.Windows = append(result.Windows, window)
		}
	} else {
		if request.WindowID >= len(batches) {
			return nil, ErrG3NativeDiscoveryInvalid
		}
		var extracted combinedExtraction
		if nativeDiscoveryDecode(request.DiscoveryRaw, &extracted) != nil || extracted.Entities == nil || extracted.Concepts == nil {
			return nil, ErrG3NativeDiscoveryInvalid
		}
		seen := map[string]bool{}
		for kind, items := range map[string][]extractedItem{"entity": extracted.Entities, "concept": extracted.Concepts} {
			for _, item := range items {
				if !nativeDiscoveryItemValid(kind, item, seen) || len(item.SourceChunks) != 0 {
					return nil, ErrG3NativeDiscoveryInvalid
				}
			}
		}
		batch := batches[request.WindowID]
		window, err := nativeDiscoveryWindow(request.WindowID, batch, request, &extracted)
		if err != nil {
			return nil, err
		}
		result.Windows = append(result.Windows, window)
		result.DiscoveryRawSHA256 = g3PlatformRawSHA256([]byte(request.DiscoveryRaw))
		if request.Phase == "snapshot" {
			items, err := nativeDiscoveryCitations(batch, extracted, seen, request.CitationRaw)
			if err != nil {
				return nil, err
			}
			result.Candidates = items
			result.CitationRawSHA256 = g3PlatformRawSHA256([]byte(request.CitationRaw))
		}
	}
	result.SnapshotSHA256, err = g3PlatformSnapshotDigest(result.Contract, result, "snapshot_sha256")
	if err != nil {
		return nil, err
	}
	authority, err := signG3PlatformSnapshot(ctx, s.signer, "weknora."+result.Contract, result.SnapshotSHA256)
	if err != nil {
		return nil, err
	}
	return &G3SignedNativeDiscoverySnapshot{Contract: strings.Replace(result.Contract, "g3-platform-", "g3-platform-signed-", 1), Snapshot: result, Authority: authority}, nil
}

func nativeDiscoveryWindow(index int, batch chunkBatch, request G3NativeDiscoveryRequest, extracted *combinedExtraction) (G3NativeDiscoveryWindow, error) {
	window := G3NativeDiscoveryWindow{WindowID: index, ChunkIDs: []string{}}
	var content strings.Builder
	for _, chunk := range batch.chunks {
		window.ChunkIDs = append(window.ChunkIDs, chunk.ID)
		content.WriteString(chunk.Content)
		content.WriteString("\n\n")
	}
	prompt := agent.WikiCandidateSlugPrompt
	data := map[string]string{"Content": content.String(), "Language": request.Language, "PreviousSlugs": "(none — candidates are not serving page identities)",
		"Granularity": string(request.Granularity), "GranularityGuidance": agent.WikiGranularityGuidance(string(request.Granularity))}
	if extracted != nil {
		prompt = agent.WikiChunkCitationPrompt
		data["CandidateSlugs"] = renderCandidateSlugsXML(extracted.Entities, extracted.Concepts)
		data["ChunksXML"] = renderChunksXML(batch)
	}
	tmpl, err := template.New("native-discovery").Parse(prompt)
	if err != nil {
		return window, err
	}
	var rendered strings.Builder
	if err := tmpl.Execute(&rendered, data); err != nil {
		return window, err
	}
	window.Prompt = types.AppendCustomPromptInstructions(rendered.String(), request.Purpose, "wiki_extraction")
	if len([]byte(window.Prompt)) > request.MaxPromptBytes {
		return window, ErrG3NativeDiscoveryInvalid
	}
	window.PromptSHA256 = g3PlatformRawSHA256([]byte(window.Prompt))
	return window, nil
}

func nativeDiscoveryDecode(raw string, target any) error {
	trimmed := strings.TrimSpace(raw)
	if strings.HasPrefix(trimmed, "```json\n") && strings.HasSuffix(trimmed, "\n```") {
		trimmed = strings.TrimSuffix(strings.TrimPrefix(trimmed, "```json\n"), "\n```")
	}
	// Reuse the public strict recursive JSON canonicalizer to reject duplicate
	// properties/non-finite numbers before the native DTO decoder sees them.
	canonical, err := types.CanonicalConceptMemberPayload830G2(json.RawMessage(trimmed))
	if err != nil {
		return ErrG3NativeDiscoveryInvalid
	}
	decoder := json.NewDecoder(strings.NewReader(string(canonical)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(target) != nil || !jsonEOF830G2(decoder) {
		return ErrG3NativeDiscoveryInvalid
	}
	return nil
}

func nativeDiscoveryItemValid(kind string, item extractedItem, seen map[string]bool) bool {
	if (kind != "entity" && kind != "concept") || strings.TrimSpace(item.Name) == "" ||
		!strings.HasPrefix(item.Slug, kind+"/") || len(item.Slug) <= len(kind)+1 || seen[item.Slug] {
		return false
	}
	seen[item.Slug] = true
	return true
}

func nativeDiscoveryCitations(batch chunkBatch, extracted combinedExtraction, seen map[string]bool, raw string) ([]G3NativeDiscoveryCandidate, error) {
	var parsed citationBatchResult
	if nativeDiscoveryDecode(raw, &parsed) != nil || parsed.Citations == nil || parsed.NewSlugs == nil {
		return nil, ErrG3NativeDiscoveryInvalid
	}
	resolve := func(handles []string) ([]string, error) {
		selected := map[string]bool{}
		if len(handles) == 0 {
			return nil, ErrG3NativeDiscoveryInvalid
		}
		for _, handle := range handles {
			id, ok := batch.handles.Resolve(handle)
			if !ok || selected[id] {
				return nil, ErrG3NativeDiscoveryInvalid
			}
			selected[id] = true
		}
		ids := []string{}
		for _, chunk := range batch.chunks {
			if selected[chunk.ID] {
				ids = append(ids, chunk.ID)
			}
		}
		return ids, nil
	}
	citations := map[string][]string{}
	for slug, handles := range parsed.Citations {
		if !seen[slug] {
			return nil, ErrG3NativeDiscoveryInvalid
		}
		ids, err := resolve(handles)
		if err != nil {
			return nil, err
		}
		citations[slug] = ids
	}
	for i := range parsed.NewSlugs {
		row := &parsed.NewSlugs[i]
		if !nativeDiscoveryItemValid(row.Type, extractedItem{Name: row.Name, Slug: row.Slug}, seen) {
			return nil, ErrG3NativeDiscoveryInvalid
		}
		ids, err := resolve(row.SourceChunks)
		if err != nil {
			return nil, err
		}
		row.SourceChunks = ids
	}
	entities, concepts, _ := mergeCitationsIntoItems(extracted.Entities, extracted.Concepts, citations, parsed.NewSlugs)
	result := []G3NativeDiscoveryCandidate{}
	for _, group := range []struct {
		kind  string
		items []extractedItem
	}{{"entity", entities}, {"concept", concepts}} {
		for _, item := range group.items {
			aliases := append([]string{}, item.Aliases...)
			chunks := append([]string{}, item.SourceChunks...)
			result = append(result, G3NativeDiscoveryCandidate{ContentOrigin: "MODEL_GENERATED", Kind: group.kind, Name: item.Name, Slug: item.Slug, Aliases: aliases,
				Description: item.Description, Details: item.Details, SourceChunks: chunks, HasSourceChunks: len(chunks) > 0})
		}
	}
	return result, nil
}
