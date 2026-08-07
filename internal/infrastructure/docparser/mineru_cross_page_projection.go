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
	minerUTermsSourceSHA256    = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
	minerUBrochureSourceSHA256 = "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
	minerURatesSourceSHA256    = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"

	minerUCrossPageContract                 = "mineru-native-cross-page-facts.v1"
	minerUCrossPageVersion                  = "3.4.4"
	minerUCrossPagePresent                  = "NATIVE_CROSS_PAGE_FACT_PRESENT"
	minerUCrossPageAbsent                   = "NATIVE_CROSS_PAGE_FACT_ABSENT"
	minerUCrossPageAmbiguous                = "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS"
	minerUCrossPageNotAvailable             = "NATIVE_CROSS_PAGE_FACT_NOT_AVAILABLE"
	minerUCrossPageMarkerProvenanceContract = "mineru-native-cross-page-marker-provenance.v1"
	minerUNativeHierarchyContract           = "mineru-native-hierarchy-provenance.v1"
	minerUNativeHierarchyCaptured           = "NATIVE_HIERARCHY_PROVENANCE_CAPTURED"
	minerUNativeHierarchyNotCaptured        = "HIERARCHY_PROVENANCE_NOT_CAPTURED"

	maxMinerUCrossPageZIPBytes       = 128 << 20
	maxMinerUCrossPageMembers        = 256
	maxMinerUCrossPageMemberBytes    = 64 << 20
	maxMinerUCrossPageExpandedBytes  = 256 << 20
	maxMinerUCrossPageCompression    = 200
	compressionRatioMinimumByteCount = 1 << 20
)

var (
	ErrMinerUCrossPageProjectionInvalid       = errors.New("MinerU native cross-page projection invalid")
	ErrMinerUCrossPageMarkerProvenanceInvalid = errors.New(
		"MinerU native cross-page marker provenance invalid",
	)
)

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

type minerUCrossPageMarkerEvidence struct {
	MarkerKind           string `json:"marker_kind"`
	PageIndex            int    `json:"page_index"`
	StructuralPath       string `json:"structural_path"`
	StructuralPathSHA256 string `json:"structural_path_sha256"`
	NodeType             string `json:"node_type"`
	LocalIndex           int    `json:"local_index"`
	MarkerSHA256         string `json:"marker_sha256"`
}

type minerUCrossPageMarkerProvenance struct {
	Contract           string                           `json:"contract"`
	SourceSHA256       string                           `json:"source_sha256"`
	ParserModel        string                           `json:"parser_model"`
	MinerUVersion      string                           `json:"mineru_version"`
	RawZIPSHA256       string                           `json:"raw_zip_sha256"`
	NativeMemberSHA256 string                           `json:"native_member_sha256"`
	MarkerCount        int                              `json:"marker_count"`
	Markers            []minerUCrossPageMarkerEvidence  `json:"markers"`
	NativeHierarchy    *minerUNativeHierarchyProvenance `json:"native_hierarchy_provenance,omitempty"`
	ReplayDigestSHA256 string                           `json:"replay_digest_sha256"`
}

type minerUNativeHierarchyNode struct {
	PageIndex            int    `json:"page_index"`
	NodeType             string `json:"node_type"`
	LocalIndex           int    `json:"local_index"`
	ReadingOrder         int    `json:"reading_order"`
	StructuralPath       string `json:"structural_path"`
	StructuralPathSHA256 string `json:"structural_path_sha256"`
	BBoxPresent          bool   `json:"bbox_present"`
	BBoxSHA256           string `json:"bbox_sha256"`
	TextLevel            *int   `json:"text_level"`
	NodePreimageSHA256   string `json:"node_preimage_sha256"`
}

type minerUNativeHierarchyProvenance struct {
	Contract             string                      `json:"contract"`
	Status               string                      `json:"status"`
	SourceSHA256         string                      `json:"source_sha256"`
	ParserModel          string                      `json:"parser_model"`
	MinerUVersion        string                      `json:"mineru_version"`
	RawZIPSHA256         string                      `json:"raw_zip_sha256"`
	NativeMemberSHA256   string                      `json:"native_member_sha256"`
	NativeMemberCategory string                      `json:"native_member_category"`
	NodeCount            int                         `json:"node_count"`
	HierarchyFieldCount  int                         `json:"hierarchy_field_count"`
	Nodes                []minerUNativeHierarchyNode `json:"nodes"`
	ReplayDigestSHA256   string                      `json:"replay_digest_sha256"`
}

type minerUNativeHierarchyNodePreimage struct {
	Contract             string `json:"contract"`
	SourceSHA256         string `json:"source_sha256"`
	ParserModel          string `json:"parser_model"`
	MinerUVersion        string `json:"mineru_version"`
	RawZIPSHA256         string `json:"raw_zip_sha256"`
	NativeMemberSHA256   string `json:"native_member_sha256"`
	PageIndex            int    `json:"page_index"`
	NodeType             string `json:"node_type"`
	LocalIndex           int    `json:"local_index"`
	ReadingOrder         int    `json:"reading_order"`
	StructuralPath       string `json:"structural_path"`
	StructuralPathSHA256 string `json:"structural_path_sha256"`
	BBoxPresent          bool   `json:"bbox_present"`
	BBoxSHA256           string `json:"bbox_sha256"`
	TextLevel            *int   `json:"text_level"`
}

type minerUNativeHierarchyReplayPreimage struct {
	Contract             string                      `json:"contract"`
	Status               string                      `json:"status"`
	SourceSHA256         string                      `json:"source_sha256"`
	ParserModel          string                      `json:"parser_model"`
	MinerUVersion        string                      `json:"mineru_version"`
	RawZIPSHA256         string                      `json:"raw_zip_sha256"`
	NativeMemberSHA256   string                      `json:"native_member_sha256"`
	NativeMemberCategory string                      `json:"native_member_category"`
	NodeCount            int                         `json:"node_count"`
	HierarchyFieldCount  int                         `json:"hierarchy_field_count"`
	Nodes                []minerUNativeHierarchyNode `json:"nodes"`
}

type minerUCrossPageMarkerDigestPreimage struct {
	Contract             string `json:"contract"`
	SourceSHA256         string `json:"source_sha256"`
	ParserModel          string `json:"parser_model"`
	MinerUVersion        string `json:"mineru_version"`
	NativeMemberSHA256   string `json:"native_member_sha256"`
	MarkerKind           string `json:"marker_kind"`
	PageIndex            int    `json:"page_index"`
	StructuralPathSHA256 string `json:"structural_path_sha256"`
	NodeType             string `json:"node_type"`
	LocalIndex           int    `json:"local_index"`
}

type minerUCrossPageMarkerReplayPreimage struct {
	Contract                    string                          `json:"contract"`
	SourceSHA256                string                          `json:"source_sha256"`
	ParserModel                 string                          `json:"parser_model"`
	MinerUVersion               string                          `json:"mineru_version"`
	RawZIPSHA256                string                          `json:"raw_zip_sha256"`
	NativeMemberSHA256          string                          `json:"native_member_sha256"`
	MarkerCount                 int                             `json:"marker_count"`
	Markers                     []minerUCrossPageMarkerEvidence `json:"markers"`
	NativeHierarchyReplaySHA256 string                          `json:"native_hierarchy_replay_sha256,omitempty"`
}

// projectMinerUCrossPageMarkerProvenanceZip emits a companion receipt without
// adding fields to mineru-native-cross-page-facts.v1. It intentionally emits no
// endpoints or relation.
func projectMinerUCrossPageMarkerProvenanceZip(
	zipData []byte,
	sourceSHA256 string,
) (*minerUCrossPageMarkerProvenance, error) {
	legacy, err := projectMinerUCrossPageZip(zipData, sourceSHA256)
	if err != nil || legacy == nil || legacy.MinerUVersion != minerUCrossPageVersion ||
		!validLowerSHA256(legacy.NativeMemberSHA256) {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	middle, err := readMinerUCrossPageMarkerMiddle(zipData)
	if err != nil {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	middleHash := sha256.Sum256(middle)
	if hex.EncodeToString(middleHash[:]) != legacy.NativeMemberSHA256 {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	markers, err := decodeMinerUCrossPageMarkerMiddle(
		middle, sourceSHA256, legacy.NativeMemberSHA256,
	)
	if err != nil {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	hierarchy, err := projectMinerUNativeHierarchyProvenance(
		middle, sourceSHA256, legacy.RawZIPSHA256, legacy.NativeMemberSHA256,
	)
	if err != nil {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	provenance := &minerUCrossPageMarkerProvenance{
		Contract:           minerUCrossPageMarkerProvenanceContract,
		SourceSHA256:       sourceSHA256,
		ParserModel:        legacy.ParserModel,
		MinerUVersion:      legacy.MinerUVersion,
		RawZIPSHA256:       legacy.RawZIPSHA256,
		NativeMemberSHA256: legacy.NativeMemberSHA256,
		MarkerCount:        len(markers),
		Markers:            markers,
		NativeHierarchy:    hierarchy,
	}
	sealMinerUCrossPageMarkerProvenance(provenance)
	if err := validateMinerUCrossPageMarkerProvenance(provenance); err != nil {
		return nil, err
	}
	return provenance, nil
}

func replayMinerUCrossPageMarkerProvenanceZip(
	zipData []byte,
	sourceSHA256 string,
	provenance *minerUCrossPageMarkerProvenance,
) error {
	if err := validateMinerUCrossPageMarkerProvenance(provenance); err != nil {
		return err
	}
	expected, err := projectMinerUCrossPageMarkerProvenanceZip(zipData, sourceSHA256)
	if err != nil {
		return ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	expectedBytes, expectedErr := json.Marshal(expected)
	actualBytes, actualErr := json.Marshal(provenance)
	if expectedErr != nil || actualErr != nil || !bytes.Equal(expectedBytes, actualBytes) {
		return ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	return nil
}

func readMinerUCrossPageMarkerMiddle(zipData []byte) ([]byte, error) {
	zr, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
	if err != nil {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	var middle []byte
	for _, file := range zr.File {
		_, category, err := validateMinerUCrossPageMember(file)
		if err != nil {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		if file.FileInfo().IsDir() || category != "middle_json" {
			continue
		}
		if middle != nil {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		middle, err = readMinerUCrossPageMember(file)
		if err != nil {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
	}
	if middle == nil {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	return middle, nil
}

func decodeMinerUCrossPageMarkerMiddle(
	raw []byte,
	sourceSHA256 string,
	nativeMemberSHA256 string,
) ([]minerUCrossPageMarkerEvidence, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var root map[string]any
	if err := decoder.Decode(&root); err != nil || decoder.Decode(&struct{}{}) != io.EOF {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	if err := rejectSensitiveMinerUKeys(root); err != nil {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	if root["_backend"] != "pipeline" || root["_version_name"] != minerUCrossPageVersion {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	pages, ok := root["pdf_info"].([]any)
	if !ok || len(pages) == 0 || len(pages) > 2000 {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	byIndex := make(map[int]map[string]any, len(pages))
	for _, rawPage := range pages {
		page, ok := rawPage.(map[string]any)
		if !ok {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		pageIndex, ok := exactJSONInt(page["page_idx"])
		if !ok || pageIndex < 0 {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		if _, exists := byIndex[pageIndex]; exists {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		byIndex[pageIndex] = page
	}
	markers := make([]minerUCrossPageMarkerEvidence, 0)
	for pageIndex := 0; pageIndex < len(pages); pageIndex++ {
		page, exists := byIndex[pageIndex]
		if !exists {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		blocks, ok := page["para_blocks"].([]any)
		if !ok {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		for blockIndex, block := range blocks {
			if err := walkMinerUCrossPageMarkerNode(
				block, sourceSHA256, nativeMemberSHA256, pageIndex,
				"p"+strconv.Itoa(pageIndex)+"/b"+strconv.Itoa(blockIndex),
				blockIndex, &markers,
			); err != nil {
				return nil, err
			}
		}
	}
	sort.Slice(markers, func(i, j int) bool {
		if markers[i].PageIndex != markers[j].PageIndex {
			return markers[i].PageIndex < markers[j].PageIndex
		}
		if markers[i].StructuralPathSHA256 != markers[j].StructuralPathSHA256 {
			return markers[i].StructuralPathSHA256 < markers[j].StructuralPathSHA256
		}
		return markers[i].MarkerKind < markers[j].MarkerKind
	})
	return markers, nil
}

func walkMinerUCrossPageMarkerNode(
	value any,
	sourceSHA256 string,
	nativeMemberSHA256 string,
	pageIndex int,
	structuralPath string,
	localIndex int,
	markers *[]minerUCrossPageMarkerEvidence,
) error {
	node, ok := value.(map[string]any)
	if !ok {
		return ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	for _, markerKind := range []string{"cross_page", "lines_deleted"} {
		marker, exists := node[markerKind]
		if !exists {
			continue
		}
		flag, ok := marker.(bool)
		if !ok {
			return ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		if !flag {
			continue
		}
		nodeType, ok := node["type"].(string)
		if !ok || !validMinerUCrossPageMarkerNodeType(nodeType) {
			return ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		pathSHA256 := domainSHA256(
			"mineru-cross-page-marker-path.v1",
			sourceSHA256+"\x00"+nativeMemberSHA256+"\x00"+structuralPath,
		)
		item := minerUCrossPageMarkerEvidence{
			MarkerKind:           markerKind,
			PageIndex:            pageIndex,
			StructuralPath:       structuralPath,
			StructuralPathSHA256: pathSHA256,
			NodeType:             nodeType,
			LocalIndex:           localIndex,
		}
		item.MarkerSHA256 = minerUCrossPageMarkerSHA256(
			sourceSHA256, nativeMemberSHA256, item,
		)
		*markers = append(*markers, item)
	}
	for _, key := range []string{"blocks", "lines", "spans"} {
		child, exists := node[key]
		if !exists {
			continue
		}
		values, ok := child.([]any)
		if !ok {
			return ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		for index, nested := range values {
			if err := walkMinerUCrossPageMarkerNode(
				nested, sourceSHA256, nativeMemberSHA256, pageIndex,
				structuralPath+"/"+key+"/"+strconv.Itoa(index), index, markers,
			); err != nil {
				return err
			}
		}
	}
	return nil
}

func validMinerUCrossPageMarkerNodeType(value string) bool {
	if value == "" || len(value) > 64 || value != strings.ToLower(value) {
		return false
	}
	for _, character := range value {
		if (character < 'a' || character > 'z') && (character < '0' || character > '9') &&
			character != '_' && character != '-' {
			return false
		}
	}
	for _, token := range []string{"secret", "token", "api_key", "apikey", "bearer", "credential", "password", "url", "path"} {
		if strings.Contains(value, token) {
			return false
		}
	}
	return true
}

func validMinerUCrossPageMarkerStructuralPath(value string, pageIndex, localIndex int) bool {
	parts := strings.Split(value, "/")
	if len(parts) < 2 || len(parts)%2 != 0 ||
		parts[0] != "p"+strconv.Itoa(pageIndex) ||
		!strings.HasPrefix(parts[1], "b") {
		return false
	}
	blockIndex, err := strconv.Atoi(strings.TrimPrefix(parts[1], "b"))
	if err != nil || blockIndex < 0 || parts[1] != "b"+strconv.Itoa(blockIndex) {
		return false
	}
	lastIndex := blockIndex
	for index := 2; index < len(parts); index += 2 {
		if parts[index] != "blocks" && parts[index] != "lines" && parts[index] != "spans" {
			return false
		}
		childIndex, err := strconv.Atoi(parts[index+1])
		if err != nil || childIndex < 0 || strconv.Itoa(childIndex) != parts[index+1] {
			return false
		}
		lastIndex = childIndex
	}
	return lastIndex == localIndex
}

func minerUCrossPageMarkerSHA256(
	sourceSHA256 string,
	nativeMemberSHA256 string,
	marker minerUCrossPageMarkerEvidence,
) string {
	preimage, _ := json.Marshal(minerUCrossPageMarkerDigestPreimage{
		Contract:             minerUCrossPageMarkerProvenanceContract,
		SourceSHA256:         sourceSHA256,
		ParserModel:          "pipeline",
		MinerUVersion:        minerUCrossPageVersion,
		NativeMemberSHA256:   nativeMemberSHA256,
		MarkerKind:           marker.MarkerKind,
		PageIndex:            marker.PageIndex,
		StructuralPathSHA256: marker.StructuralPathSHA256,
		NodeType:             marker.NodeType,
		LocalIndex:           marker.LocalIndex,
	})
	return domainSHA256("mineru-cross-page-marker-evidence.v1", string(preimage))
}

func projectMinerUNativeHierarchyProvenance(
	raw []byte,
	sourceSHA256, rawZIPSHA256, nativeMemberSHA256 string,
) (*minerUNativeHierarchyProvenance, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var root map[string]any
	if err := decoder.Decode(&root); err != nil || decoder.Decode(&struct{}{}) != io.EOF ||
		rejectSensitiveMinerUKeys(root) != nil || root["_backend"] != "pipeline" ||
		root["_version_name"] != minerUCrossPageVersion {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	pages, ok := root["pdf_info"].([]any)
	if !ok || len(pages) == 0 || len(pages) > 2000 {
		return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	byIndex := make(map[int]map[string]any, len(pages))
	for _, rawPage := range pages {
		page, ok := rawPage.(map[string]any)
		if !ok {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		pageIndex, ok := exactJSONInt(page["page_idx"])
		if !ok || pageIndex < 0 {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		if _, duplicate := byIndex[pageIndex]; duplicate {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		byIndex[pageIndex] = page
	}
	nodes := make([]minerUNativeHierarchyNode, 0)
	hierarchyCount := 0
	readingOrder := 0
	for pageIndex := 0; pageIndex < len(pages); pageIndex++ {
		page, exists := byIndex[pageIndex]
		if !exists {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		blocks, ok := page["para_blocks"].([]any)
		if !ok {
			return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		for localIndex, rawBlock := range blocks {
			block, ok := rawBlock.(map[string]any)
			if !ok {
				return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
			}
			nodeType, ok := block["type"].(string)
			if !ok || !validMinerUNativeHierarchyNodeType(nodeType) {
				return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
			}
			structuralPath := "p" + strconv.Itoa(pageIndex) + "/b" + strconv.Itoa(localIndex)
			structuralPathSHA256 := domainSHA256(
				"mineru-cross-page-marker-path.v1",
				sourceSHA256+"\x00"+nativeMemberSHA256+"\x00"+structuralPath,
			)
			bboxPresent, bboxSHA256, err := minerUNativeHierarchyBBox(block)
			if err != nil {
				return nil, err
			}
			var textLevel *int
			rawLevel, levelPresent := block["text_level"]
			if nativeLevel, nativeLevelPresent := block["level"]; nativeLevelPresent {
				if levelPresent || nodeType != "title" {
					return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
				}
				rawLevel, levelPresent = nativeLevel, true
			}
			if levelPresent {
				level, ok := exactJSONInt(rawLevel)
				if !ok || level < 1 || level > 32 {
					return nil, ErrMinerUCrossPageMarkerProvenanceInvalid
				}
				textLevel = &level
				hierarchyCount++
			}
			node := minerUNativeHierarchyNode{
				PageIndex: pageIndex, NodeType: nodeType, LocalIndex: localIndex,
				ReadingOrder: readingOrder, StructuralPath: structuralPath,
				StructuralPathSHA256: structuralPathSHA256, BBoxPresent: bboxPresent,
				BBoxSHA256: bboxSHA256, TextLevel: textLevel,
			}
			node.NodePreimageSHA256 = minerUNativeHierarchyNodeSHA256(
				sourceSHA256, rawZIPSHA256, nativeMemberSHA256, node,
			)
			nodes = append(nodes, node)
			readingOrder++
		}
	}
	status := minerUNativeHierarchyNotCaptured
	if hierarchyCount > 0 {
		status = minerUNativeHierarchyCaptured
	}
	provenance := &minerUNativeHierarchyProvenance{
		Contract: minerUNativeHierarchyContract, Status: status,
		SourceSHA256: sourceSHA256, ParserModel: "pipeline",
		MinerUVersion: minerUCrossPageVersion, RawZIPSHA256: rawZIPSHA256,
		NativeMemberSHA256: nativeMemberSHA256, NativeMemberCategory: "middle_json",
		NodeCount: len(nodes), HierarchyFieldCount: hierarchyCount, Nodes: nodes,
	}
	sealMinerUNativeHierarchyProvenance(provenance)
	if err := validateMinerUNativeHierarchyProvenance(provenance); err != nil {
		return nil, err
	}
	return provenance, nil
}

func validMinerUNativeHierarchyNodeType(value string) bool {
	allowed := map[string]bool{
		"text": true, "title": true, "section": true, "index": true, "table": true,
		"image": true, "chart": true, "equation": true, "interline_equation": true,
		"code": true, "list": true, "header": true, "footer": true,
		"page_header": true, "page_footer": true, "page_number": true,
		"aside_text": true, "page_footnote": true,
	}
	return allowed[value]
}

func minerUNativeHierarchyBBox(block map[string]any) (bool, string, error) {
	raw, present := block["bbox"]
	if !present {
		return false, domainSHA256("mineru-native-hierarchy-bbox.v1", "null"), nil
	}
	values, ok := raw.([]any)
	if !ok || len(values) != 4 {
		return false, "", ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	for _, value := range values {
		number, ok := value.(json.Number)
		if !ok {
			return false, "", ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		if _, err := strconv.ParseFloat(number.String(), 64); err != nil {
			return false, "", ErrMinerUCrossPageMarkerProvenanceInvalid
		}
	}
	preimage, _ := json.Marshal(values)
	return true, domainSHA256("mineru-native-hierarchy-bbox.v1", string(preimage)), nil
}

func minerUNativeHierarchyNodeSHA256(
	sourceSHA256, rawZIPSHA256, nativeMemberSHA256 string,
	node minerUNativeHierarchyNode,
) string {
	preimage, _ := json.Marshal(minerUNativeHierarchyNodePreimage{
		Contract: minerUNativeHierarchyContract + ".node", SourceSHA256: sourceSHA256,
		ParserModel: "pipeline", MinerUVersion: minerUCrossPageVersion,
		RawZIPSHA256: rawZIPSHA256, NativeMemberSHA256: nativeMemberSHA256,
		PageIndex: node.PageIndex, NodeType: node.NodeType, LocalIndex: node.LocalIndex,
		ReadingOrder: node.ReadingOrder, StructuralPath: node.StructuralPath,
		StructuralPathSHA256: node.StructuralPathSHA256, BBoxPresent: node.BBoxPresent,
		BBoxSHA256: node.BBoxSHA256, TextLevel: node.TextLevel,
	})
	return domainSHA256("mineru-native-hierarchy-node.v1", string(preimage))
}

func sealMinerUNativeHierarchyProvenance(provenance *minerUNativeHierarchyProvenance) {
	preimage, _ := json.Marshal(minerUNativeHierarchyReplayPreimage{
		Contract: provenance.Contract, Status: provenance.Status,
		SourceSHA256: provenance.SourceSHA256, ParserModel: provenance.ParserModel,
		MinerUVersion: provenance.MinerUVersion, RawZIPSHA256: provenance.RawZIPSHA256,
		NativeMemberSHA256:   provenance.NativeMemberSHA256,
		NativeMemberCategory: provenance.NativeMemberCategory,
		NodeCount:            provenance.NodeCount, HierarchyFieldCount: provenance.HierarchyFieldCount,
		Nodes: provenance.Nodes,
	})
	provenance.ReplayDigestSHA256 = domainSHA256(
		"mineru-native-hierarchy-provenance-replay.v1", string(preimage),
	)
}

func validateMinerUNativeHierarchyProvenance(provenance *minerUNativeHierarchyProvenance) error {
	if provenance == nil || provenance.Contract != minerUNativeHierarchyContract ||
		(provenance.Status != minerUNativeHierarchyCaptured &&
			provenance.Status != minerUNativeHierarchyNotCaptured) ||
		provenance.ParserModel != "pipeline" || provenance.MinerUVersion != minerUCrossPageVersion ||
		provenance.NativeMemberCategory != "middle_json" ||
		!validLowerSHA256(provenance.SourceSHA256) || !validLowerSHA256(provenance.RawZIPSHA256) ||
		!validLowerSHA256(provenance.NativeMemberSHA256) ||
		!validLowerSHA256(provenance.ReplayDigestSHA256) ||
		provenance.NodeCount != len(provenance.Nodes) || provenance.NodeCount == 0 {
		return ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	hierarchyCount := 0
	seen := make(map[string]struct{}, len(provenance.Nodes))
	for index, node := range provenance.Nodes {
		if node.PageIndex < 0 || node.LocalIndex < 0 || node.ReadingOrder != index ||
			!validMinerUNativeHierarchyNodeType(node.NodeType) ||
			!validLowerSHA256(node.StructuralPathSHA256) ||
			!validLowerSHA256(node.BBoxSHA256) || !validLowerSHA256(node.NodePreimageSHA256) ||
			node.StructuralPath != "p"+strconv.Itoa(node.PageIndex)+"/b"+strconv.Itoa(node.LocalIndex) ||
			node.NodePreimageSHA256 != minerUNativeHierarchyNodeSHA256(
				provenance.SourceSHA256, provenance.RawZIPSHA256,
				provenance.NativeMemberSHA256, node,
			) {
			return ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		if node.TextLevel != nil {
			if *node.TextLevel < 1 || *node.TextLevel > 32 {
				return ErrMinerUCrossPageMarkerProvenanceInvalid
			}
			hierarchyCount++
		}
		if _, duplicate := seen[node.StructuralPathSHA256]; duplicate {
			return ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		seen[node.StructuralPathSHA256] = struct{}{}
	}
	if hierarchyCount != provenance.HierarchyFieldCount ||
		(provenance.Status == minerUNativeHierarchyCaptured) != (hierarchyCount > 0) {
		return ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	copy := *provenance
	copy.Nodes = append([]minerUNativeHierarchyNode(nil), provenance.Nodes...)
	sort.Slice(copy.Nodes, func(i, j int) bool { return copy.Nodes[i].ReadingOrder < copy.Nodes[j].ReadingOrder })
	copy.ReplayDigestSHA256 = ""
	sealMinerUNativeHierarchyProvenance(&copy)
	if copy.ReplayDigestSHA256 != provenance.ReplayDigestSHA256 {
		return ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	return nil
}

func sealMinerUCrossPageMarkerProvenance(provenance *minerUCrossPageMarkerProvenance) {
	hierarchyReplaySHA256 := ""
	if provenance.NativeHierarchy != nil {
		hierarchyReplaySHA256 = provenance.NativeHierarchy.ReplayDigestSHA256
	}
	preimage, _ := json.Marshal(minerUCrossPageMarkerReplayPreimage{
		Contract:                    provenance.Contract,
		SourceSHA256:                provenance.SourceSHA256,
		ParserModel:                 provenance.ParserModel,
		MinerUVersion:               provenance.MinerUVersion,
		RawZIPSHA256:                provenance.RawZIPSHA256,
		NativeMemberSHA256:          provenance.NativeMemberSHA256,
		MarkerCount:                 provenance.MarkerCount,
		Markers:                     provenance.Markers,
		NativeHierarchyReplaySHA256: hierarchyReplaySHA256,
	})
	provenance.ReplayDigestSHA256 = domainSHA256(
		"mineru-cross-page-marker-provenance-replay.v1", string(preimage),
	)
}

func validateMinerUCrossPageMarkerProvenance(provenance *minerUCrossPageMarkerProvenance) error {
	if provenance == nil || provenance.Contract != minerUCrossPageMarkerProvenanceContract ||
		provenance.ParserModel != "pipeline" || provenance.MinerUVersion != minerUCrossPageVersion ||
		!validLowerSHA256(provenance.SourceSHA256) ||
		!validLowerSHA256(provenance.RawZIPSHA256) ||
		!validLowerSHA256(provenance.NativeMemberSHA256) ||
		!validLowerSHA256(provenance.ReplayDigestSHA256) ||
		provenance.MarkerCount != len(provenance.Markers) {
		return ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	if provenance.NativeHierarchy != nil {
		if validateMinerUNativeHierarchyProvenance(provenance.NativeHierarchy) != nil ||
			provenance.NativeHierarchy.SourceSHA256 != provenance.SourceSHA256 ||
			provenance.NativeHierarchy.ParserModel != provenance.ParserModel ||
			provenance.NativeHierarchy.MinerUVersion != provenance.MinerUVersion ||
			provenance.NativeHierarchy.RawZIPSHA256 != provenance.RawZIPSHA256 ||
			provenance.NativeHierarchy.NativeMemberSHA256 != provenance.NativeMemberSHA256 {
			return ErrMinerUCrossPageMarkerProvenanceInvalid
		}
	}
	if _, targeted := minerUCrossPageRequiredCapability(provenance.SourceSHA256); !targeted {
		return ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	seen := make(map[string]struct{}, len(provenance.Markers))
	for index, marker := range provenance.Markers {
		if (marker.MarkerKind != "cross_page" && marker.MarkerKind != "lines_deleted") ||
			marker.PageIndex < 0 || marker.LocalIndex < 0 ||
			!validMinerUCrossPageMarkerStructuralPath(
				marker.StructuralPath, marker.PageIndex, marker.LocalIndex,
			) ||
			!validMinerUCrossPageMarkerNodeType(marker.NodeType) ||
			!validLowerSHA256(marker.StructuralPathSHA256) ||
			marker.StructuralPathSHA256 != domainSHA256(
				"mineru-cross-page-marker-path.v1",
				provenance.SourceSHA256+"\x00"+provenance.NativeMemberSHA256+"\x00"+
					marker.StructuralPath,
			) ||
			!validLowerSHA256(marker.MarkerSHA256) ||
			marker.MarkerSHA256 != minerUCrossPageMarkerSHA256(
				provenance.SourceSHA256, provenance.NativeMemberSHA256, marker,
			) {
			return ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		identity := marker.MarkerKind + "\x00" + marker.StructuralPathSHA256
		if _, duplicate := seen[identity]; duplicate {
			return ErrMinerUCrossPageMarkerProvenanceInvalid
		}
		seen[identity] = struct{}{}
		if index > 0 {
			previous := provenance.Markers[index-1]
			if previous.PageIndex > marker.PageIndex ||
				(previous.PageIndex == marker.PageIndex && previous.StructuralPathSHA256 > marker.StructuralPathSHA256) ||
				(previous.PageIndex == marker.PageIndex && previous.StructuralPathSHA256 == marker.StructuralPathSHA256 &&
					previous.MarkerKind >= marker.MarkerKind) {
				return ErrMinerUCrossPageMarkerProvenanceInvalid
			}
		}
	}
	copy := *provenance
	copy.ReplayDigestSHA256 = ""
	sealMinerUCrossPageMarkerProvenance(&copy)
	if copy.ReplayDigestSHA256 != provenance.ReplayDigestSHA256 {
		return ErrMinerUCrossPageMarkerProvenanceInvalid
	}
	return nil
}

func validateMinerUCrossPageCustodyPair(
	facts *minerUCrossPageProjection,
	markers *minerUCrossPageMarkerProvenance,
	sourceSHA256 string,
) error {
	_, targeted := minerUCrossPageRequiredCapability(sourceSHA256)
	if !targeted {
		if facts != nil || markers != nil {
			return ErrMinerUCrossPageProjectionInvalid
		}
		return nil
	}
	if facts == nil || markers == nil ||
		validateMinerUCrossPageProjection(facts, sourceSHA256) != nil ||
		validateMinerUCrossPageMarkerProvenance(markers) != nil ||
		facts.SourceSHA256 != markers.SourceSHA256 ||
		facts.ParserModel != markers.ParserModel ||
		facts.MinerUVersion != markers.MinerUVersion ||
		facts.RawZIPSHA256 != markers.RawZIPSHA256 ||
		facts.NativeMemberSHA256 != markers.NativeMemberSHA256 ||
		facts.AmbiguousMarkerCount != markers.MarkerCount {
		return ErrMinerUCrossPageProjectionInvalid
	}
	return nil
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
	case minerUTermsSourceSHA256, minerUBrochureSourceSHA256:
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
	case base == "layout.json":
		category = "middle_json"
	case strings.HasSuffix(base, "_layout.pdf"):
		category = "layout_pdf"
	case strings.HasSuffix(base, "_origin.pdf"):
		category = "origin_pdf"
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
