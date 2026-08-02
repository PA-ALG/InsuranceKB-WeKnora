package docparser

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"path"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

const (
	minerUTermsSourceSHA256 = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
	minerURatesSourceSHA256 = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"

	minerUCrossPageContract     = "mineru-native-cross-page-facts.v1"
	minerUCrossPageVersion      = "3.4.4"
	minerUCrossPagePresent      = "NATIVE_CROSS_PAGE_FACT_PRESENT"
	minerUCrossPageAbsent       = "NATIVE_CROSS_PAGE_FACT_ABSENT"
	minerUCrossPageAmbiguous    = "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS"
	minerUCrossPageNotAvailable = "NATIVE_CROSS_PAGE_FACT_NOT_AVAILABLE"

	maxMinerUCrossPageZIPBytes       = 128 << 20
	maxMinerUCrossPageMembers        = 256
	maxMinerUCrossPageMemberBytes    = 64 << 20
	maxMinerUCrossPageExpandedBytes  = 256 << 20
	maxMinerUCrossPageCompression    = 200
	compressionRatioMinimumByteCount = 1 << 20
)

var ErrMinerUCrossPageProjectionInvalid = errors.New("MinerU native cross-page projection invalid")

type minerUCrossPageRelation struct {
	Kind            string `json:"kind"`
	SourcePageIndex int    `json:"source_page_index"`
	TargetPageIndex int    `json:"target_page_index"`
	SourceIDHash    string `json:"source_id_hash"`
	TargetIDHash    string `json:"target_id_hash"`
}

type minerUCrossPageMember struct {
	Category string `json:"category"`
	Size     uint64 `json:"size"`
	SHA256   string `json:"sha256"`
}

type minerUCrossPageProjection struct {
	Contract                   string                    `json:"contract"`
	Status                     string                    `json:"status"`
	RequiredCapability         string                    `json:"required_capability"`
	SourceSHA256               string                    `json:"source_sha256"`
	ParserModel                string                    `json:"parser_model"`
	MinerUVersion              string                    `json:"mineru_version"`
	RawZIPSHA256               string                    `json:"raw_zip_sha256"`
	NativeMemberSHA256         string                    `json:"native_member_sha256,omitempty"`
	MemberInventorySHA256      string                    `json:"member_inventory_sha256"`
	ProjectionSHA256           string                    `json:"projection_sha256"`
	RelationCount              int                       `json:"relation_count"`
	AmbiguousMarkerCount       int                       `json:"ambiguous_marker_count"`
	AmbiguousObservationHashes []string                  `json:"ambiguous_observation_hashes"`
	Members                    []minerUCrossPageMember   `json:"members"`
	Relations                  []minerUCrossPageRelation `json:"relations"`
}

type minerUCrossPageSemantic struct {
	Contract                   string                    `json:"contract"`
	Status                     string                    `json:"status"`
	RequiredCapability         string                    `json:"required_capability"`
	SourceSHA256               string                    `json:"source_sha256"`
	ParserModel                string                    `json:"parser_model"`
	MinerUVersion              string                    `json:"mineru_version"`
	RelationCount              int                       `json:"relation_count"`
	AmbiguousMarkerCount       int                       `json:"ambiguous_marker_count"`
	AmbiguousObservationHashes []string                  `json:"ambiguous_observation_hashes"`
	Relations                  []minerUCrossPageRelation `json:"relations"`
}

func projectMinerUCrossPageZip(zipData []byte, sourceSHA256 string) (*minerUCrossPageProjection, error) {
	required, ok := minerUCrossPageRequiredCapability(sourceSHA256)
	if !ok || len(zipData) == 0 || len(zipData) > maxMinerUCrossPageZIPBytes {
		return nil, fmt.Errorf("%w: source or ZIP identity", ErrMinerUCrossPageProjectionInvalid)
	}
	zr, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
	if err != nil || len(zr.File) == 0 || len(zr.File) > maxMinerUCrossPageMembers {
		return nil, fmt.Errorf("%w: ZIP envelope", ErrMinerUCrossPageProjectionInvalid)
	}

	seen := make(map[string]struct{}, len(zr.File))
	members := make([]minerUCrossPageMember, 0, len(zr.File))
	var middle []byte
	var expanded uint64
	for _, file := range zr.File {
		normalized, category, err := validateMinerUCrossPageMember(file)
		if err != nil {
			return nil, err
		}
		identity := strings.ToLower(normalized)
		if _, exists := seen[identity]; exists {
			return nil, fmt.Errorf("%w: duplicate ZIP member", ErrMinerUCrossPageProjectionInvalid)
		}
		seen[identity] = struct{}{}
		if file.FileInfo().IsDir() {
			continue
		}
		expanded += file.UncompressedSize64
		if expanded > maxMinerUCrossPageExpandedBytes {
			return nil, fmt.Errorf("%w: expanded ZIP budget", ErrMinerUCrossPageProjectionInvalid)
		}
		payload, err := readMinerUCrossPageMember(file)
		if err != nil {
			return nil, err
		}
		hash := sha256.Sum256(payload)
		members = append(members, minerUCrossPageMember{
			Category: category, Size: uint64(len(payload)), SHA256: hex.EncodeToString(hash[:]),
		})
		if category == "middle_json" {
			if middle != nil {
				return nil, fmt.Errorf("%w: multiple middle members", ErrMinerUCrossPageProjectionInvalid)
			}
			middle = payload
		}
	}
	sort.Slice(members, func(i, j int) bool {
		if members[i].Category != members[j].Category {
			return members[i].Category < members[j].Category
		}
		if members[i].SHA256 != members[j].SHA256 {
			return members[i].SHA256 < members[j].SHA256
		}
		return members[i].Size < members[j].Size
	})
	inventoryBytes, _ := json.Marshal(members)
	inventoryHash := sha256.Sum256(inventoryBytes)
	rawHash := sha256.Sum256(zipData)
	projection := &minerUCrossPageProjection{
		Contract: minerUCrossPageContract, RequiredCapability: required,
		SourceSHA256: sourceSHA256, ParserModel: "pipeline", MinerUVersion: minerUCrossPageVersion,
		RawZIPSHA256:          hex.EncodeToString(rawHash[:]),
		MemberInventorySHA256: hex.EncodeToString(inventoryHash[:]), Members: members,
		Relations: []minerUCrossPageRelation{},
	}
	if middle == nil {
		projection.Status = minerUCrossPageNotAvailable
		sealMinerUCrossPageProjection(projection)
		return projection, nil
	}
	middleHash := sha256.Sum256(middle)
	projection.NativeMemberSHA256 = hex.EncodeToString(middleHash[:])
	observations, versionAvailable, err := decodeMinerUCrossPageMiddle(middle, sourceSHA256)
	if err != nil {
		return nil, err
	}
	if !versionAvailable {
		projection.Status = minerUCrossPageNotAvailable
		sealMinerUCrossPageProjection(projection)
		return projection, nil
	}
	projection.AmbiguousObservationHashes = observations
	projection.AmbiguousMarkerCount = len(observations)
	if len(observations) > 0 {
		projection.Status = minerUCrossPageAmbiguous
	} else {
		projection.Status = minerUCrossPageAbsent
	}
	sealMinerUCrossPageProjection(projection)
	return projection, nil
}

func minerUCrossPageRequiredCapability(sourceSHA256 string) (string, bool) {
	switch sourceSHA256 {
	case minerUTermsSourceSHA256:
		return "cross_page_sections", true
	case minerURatesSourceSHA256:
		return "cross_page_tables", true
	default:
		return "", false
	}
}

func validateMinerUCrossPageMember(file *zip.File) (string, string, error) {
	name := file.Name
	if name == "" || !utf8.ValidString(name) || strings.Contains(name, "\\") || strings.ContainsRune(name, '\x00') {
		return "", "", fmt.Errorf("%w: member name", ErrMinerUCrossPageProjectionInvalid)
	}
	normalized := path.Clean(name)
	if normalized == "." || normalized == ".." || path.IsAbs(normalized) || strings.HasPrefix(normalized, "../") ||
		normalized != strings.TrimSuffix(name, "/") {
		return "", "", fmt.Errorf("%w: unsafe member path", ErrMinerUCrossPageProjectionInvalid)
	}
	lower := strings.ToLower(normalized)
	for _, token := range []string{"secret", "token", "api_key", "apikey", "authorization", "bearer", "credential", "password", "signed_url", ".env"} {
		if strings.Contains(lower, token) {
			return "", "", fmt.Errorf("%w: sensitive member name", ErrMinerUCrossPageProjectionInvalid)
		}
	}
	mode := file.Mode()
	if mode.IsDir() {
		return normalized, "directory", nil
	}
	if !mode.IsRegular() {
		return "", "", fmt.Errorf("%w: unsupported member class", ErrMinerUCrossPageProjectionInvalid)
	}
	if file.Flags&0x1 != 0 {
		return "", "", fmt.Errorf("%w: encrypted member", ErrMinerUCrossPageProjectionInvalid)
	}
	if file.UncompressedSize64 > maxMinerUCrossPageMemberBytes ||
		(file.UncompressedSize64 > compressionRatioMinimumByteCount &&
			(file.CompressedSize64 == 0 || file.UncompressedSize64/file.CompressedSize64 > maxMinerUCrossPageCompression)) {
		return "", "", fmt.Errorf("%w: member size or compression ratio", ErrMinerUCrossPageProjectionInvalid)
	}
	base := path.Base(lower)
	var category string
	switch {
	case strings.HasSuffix(base, "_middle.json"):
		category = "middle_json"
	case strings.HasSuffix(base, "_content_list_v2.json"):
		category = "content_list_v2_json"
	case strings.HasSuffix(base, "_content_list.json"):
		category = "content_list_json"
	case strings.HasSuffix(base, "_model.json"):
		category = "model_json"
	case strings.HasSuffix(base, "_layout.pdf"):
		category = "layout_pdf"
	case strings.HasSuffix(base, "_span.pdf"):
		category = "span_pdf"
	case strings.HasSuffix(base, ".md"):
		category = "markdown"
	case strings.HasSuffix(base, ".png"), strings.HasSuffix(base, ".jpg"),
		strings.HasSuffix(base, ".jpeg"), strings.HasSuffix(base, ".webp"):
		category = "image"
	default:
		return "", "", fmt.Errorf("%w: unsupported member class", ErrMinerUCrossPageProjectionInvalid)
	}
	return normalized, category, nil
}

func readMinerUCrossPageMember(file *zip.File) ([]byte, error) {
	reader, err := file.Open()
	if err != nil {
		return nil, fmt.Errorf("%w: open member", ErrMinerUCrossPageProjectionInvalid)
	}
	defer reader.Close()
	payload, err := io.ReadAll(io.LimitReader(reader, maxMinerUCrossPageMemberBytes+1))
	if err != nil || len(payload) > maxMinerUCrossPageMemberBytes || uint64(len(payload)) != file.UncompressedSize64 {
		return nil, fmt.Errorf("%w: read member", ErrMinerUCrossPageProjectionInvalid)
	}
	return payload, nil
}

func decodeMinerUCrossPageMiddle(raw []byte, sourceSHA256 string) ([]string, bool, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var root map[string]any
	if err := decoder.Decode(&root); err != nil {
		return nil, false, fmt.Errorf("%w: decode middle", ErrMinerUCrossPageProjectionInvalid)
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return nil, false, fmt.Errorf("%w: trailing middle data", ErrMinerUCrossPageProjectionInvalid)
	}
	if err := rejectSensitiveMinerUKeys(root); err != nil {
		return nil, false, err
	}
	backend, backendOK := root["_backend"].(string)
	version, versionOK := root["_version_name"].(string)
	if !backendOK || !versionOK || backend != "pipeline" || version != minerUCrossPageVersion {
		return nil, false, nil
	}
	pages, ok := root["pdf_info"].([]any)
	if !ok || len(pages) == 0 || len(pages) > 2000 {
		return nil, false, fmt.Errorf("%w: pdf_info", ErrMinerUCrossPageProjectionInvalid)
	}
	byIndex := make(map[int]map[string]any, len(pages))
	for _, rawPage := range pages {
		page, ok := rawPage.(map[string]any)
		if !ok {
			return nil, false, fmt.Errorf("%w: page", ErrMinerUCrossPageProjectionInvalid)
		}
		pageIndex, ok := exactJSONInt(page["page_idx"])
		if !ok || pageIndex < 0 {
			return nil, false, fmt.Errorf("%w: page index", ErrMinerUCrossPageProjectionInvalid)
		}
		if _, duplicate := byIndex[pageIndex]; duplicate {
			return nil, false, fmt.Errorf("%w: duplicate page", ErrMinerUCrossPageProjectionInvalid)
		}
		byIndex[pageIndex] = page
	}
	for pageIndex := 0; pageIndex < len(pages); pageIndex++ {
		if _, ok := byIndex[pageIndex]; !ok {
			return nil, false, fmt.Errorf("%w: non-contiguous pages", ErrMinerUCrossPageProjectionInvalid)
		}
	}
	observations := make([]string, 0)
	for pageIndex := 0; pageIndex < len(pages); pageIndex++ {
		blocks, ok := byIndex[pageIndex]["para_blocks"].([]any)
		if !ok {
			return nil, false, fmt.Errorf("%w: para_blocks", ErrMinerUCrossPageProjectionInvalid)
		}
		for blockIndex, block := range blocks {
			if err := walkMinerUCrossPageNode(block, sourceSHA256,
				"p"+strconv.Itoa(pageIndex)+"/b"+strconv.Itoa(blockIndex), &observations); err != nil {
				return nil, false, err
			}
		}
	}
	sort.Strings(observations)
	return observations, true, nil
}

func walkMinerUCrossPageNode(value any, sourceSHA256, structuralPath string, observations *[]string) error {
	switch node := value.(type) {
	case []any:
		for index, child := range node {
			if err := walkMinerUCrossPageNode(child, sourceSHA256,
				structuralPath+"/"+strconv.Itoa(index), observations); err != nil {
				return err
			}
		}
	case map[string]any:
		if marker, exists := node["cross_page"]; exists {
			flag, ok := marker.(bool)
			if !ok {
				return fmt.Errorf("%w: cross_page marker type", ErrMinerUCrossPageProjectionInvalid)
			}
			if flag {
				*observations = append(*observations,
					domainSHA256("mineru-cross-page-ambiguous.v1", sourceSHA256+"\x00cross_page\x00"+structuralPath))
			}
		}
		if marker, exists := node["lines_deleted"]; exists {
			flag, ok := marker.(bool)
			if !ok {
				return fmt.Errorf("%w: lines_deleted marker type", ErrMinerUCrossPageProjectionInvalid)
			}
			if flag {
				*observations = append(*observations,
					domainSHA256("mineru-cross-page-ambiguous.v1", sourceSHA256+"\x00lines_deleted\x00"+structuralPath))
			}
		}
		for _, key := range []string{"blocks", "lines", "spans"} {
			if child, exists := node[key]; exists {
				if _, ok := child.([]any); !ok {
					return fmt.Errorf("%w: structural list %s", ErrMinerUCrossPageProjectionInvalid, key)
				}
				if err := walkMinerUCrossPageNode(child, sourceSHA256,
					structuralPath+"/"+key, observations); err != nil {
					return err
				}
			}
		}
	default:
		return fmt.Errorf("%w: structural node", ErrMinerUCrossPageProjectionInvalid)
	}
	return nil
}

func exactJSONInt(value any) (int, bool) {
	number, ok := value.(json.Number)
	if !ok || strings.ContainsAny(number.String(), ".eE") {
		return 0, false
	}
	parsed, err := strconv.Atoi(number.String())
	return parsed, err == nil
}

func rejectSensitiveMinerUKeys(value any) error {
	switch node := value.(type) {
	case []any:
		for _, child := range node {
			if err := rejectSensitiveMinerUKeys(child); err != nil {
				return err
			}
		}
	case map[string]any:
		for key, child := range node {
			lower := strings.ToLower(key)
			for _, token := range []string{"secret", "token", "api_key", "apikey", "authorization", "bearer", "credential", "password", "signed_url"} {
				if strings.Contains(lower, token) {
					return fmt.Errorf("%w: sensitive JSON key", ErrMinerUCrossPageProjectionInvalid)
				}
			}
			if err := rejectSensitiveMinerUKeys(child); err != nil {
				return err
			}
		}
	}
	return nil
}

func sealMinerUCrossPageProjection(projection *minerUCrossPageProjection) {
	semantic := minerUCrossPageSemantic{
		Contract: projection.Contract, Status: projection.Status,
		RequiredCapability: projection.RequiredCapability, SourceSHA256: projection.SourceSHA256,
		ParserModel: projection.ParserModel, MinerUVersion: projection.MinerUVersion,
		RelationCount: projection.RelationCount, AmbiguousMarkerCount: projection.AmbiguousMarkerCount,
		AmbiguousObservationHashes: projection.AmbiguousObservationHashes, Relations: projection.Relations,
	}
	preimage, _ := json.Marshal(semantic)
	hash := sha256.Sum256(preimage)
	projection.ProjectionSHA256 = hex.EncodeToString(hash[:])
}

func validateMinerUCrossPageProjection(projection *minerUCrossPageProjection, sourceSHA256 string) error {
	required, targeted := minerUCrossPageRequiredCapability(sourceSHA256)
	if projection == nil {
		return nil
	}
	if !targeted || projection.Contract != minerUCrossPageContract || projection.SourceSHA256 != sourceSHA256 ||
		projection.RequiredCapability != required || projection.ParserModel != "pipeline" ||
		projection.MinerUVersion != minerUCrossPageVersion || !validLowerSHA256(projection.RawZIPSHA256) ||
		!validLowerSHA256(projection.MemberInventorySHA256) || !validLowerSHA256(projection.ProjectionSHA256) ||
		projection.RelationCount != len(projection.Relations) {
		return ErrMinerUCrossPageProjectionInvalid
	}
	if projection.Status != minerUCrossPageNotAvailable && !validLowerSHA256(projection.NativeMemberSHA256) {
		return ErrMinerUCrossPageProjectionInvalid
	}
	if projection.Status != minerUCrossPagePresent && projection.Status != minerUCrossPageAbsent &&
		projection.Status != minerUCrossPageAmbiguous && projection.Status != minerUCrossPageNotAvailable {
		return ErrMinerUCrossPageProjectionInvalid
	}
	if projection.AmbiguousMarkerCount != len(projection.AmbiguousObservationHashes) {
		return ErrMinerUCrossPageProjectionInvalid
	}
	for _, observationHash := range projection.AmbiguousObservationHashes {
		if !validLowerSHA256(observationHash) {
			return ErrMinerUCrossPageProjectionInvalid
		}
	}
	if (projection.Status == minerUCrossPagePresent && len(projection.Relations) == 0) ||
		(projection.Status == minerUCrossPageAbsent && (len(projection.Relations) != 0 || projection.AmbiguousMarkerCount != 0)) ||
		(projection.Status == minerUCrossPageAmbiguous && (len(projection.Relations) != 0 || projection.AmbiguousMarkerCount == 0)) ||
		(projection.Status == minerUCrossPageNotAvailable && len(projection.Relations) != 0) {
		return ErrMinerUCrossPageProjectionInvalid
	}
	for _, relation := range projection.Relations {
		if relation.SourcePageIndex <= relation.TargetPageIndex || relation.TargetPageIndex < 0 ||
			!validLowerSHA256(relation.SourceIDHash) || !validLowerSHA256(relation.TargetIDHash) ||
			(relation.Kind != "section" && relation.Kind != "table") ||
			(required == "cross_page_sections" && relation.Kind != "section") ||
			(required == "cross_page_tables" && relation.Kind != "table") {
			return ErrMinerUCrossPageProjectionInvalid
		}
	}
	inventoryBytes, _ := json.Marshal(projection.Members)
	inventoryHash := sha256.Sum256(inventoryBytes)
	if hex.EncodeToString(inventoryHash[:]) != projection.MemberInventorySHA256 {
		return ErrMinerUCrossPageProjectionInvalid
	}
	copy := *projection
	copy.ProjectionSHA256 = ""
	sealMinerUCrossPageProjection(&copy)
	if copy.ProjectionSHA256 != projection.ProjectionSHA256 {
		return ErrMinerUCrossPageProjectionInvalid
	}
	return nil
}
