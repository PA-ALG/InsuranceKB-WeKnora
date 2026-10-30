package capture

import (
	"bytes"
	"strings"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
	"github.com/Tencent/WeKnora/internal/types"
)

// Office builds the capture of an Office original from its bytes (S11b): the extracted structure as
// the native artifact, the page texts joined by a blank line as the captured Markdown, and one range
// per non-empty page. It never calls a parser; the upstream parse of the same file is untouched.
func Office(fileType string, data []byte) (*types.ReadResult, []types.ParsedChunk, error) {
	structure, err := ooxml.Extract(fileType, data)
	if err != nil {
		return nil, nil, err
	}
	encoded, err := ooxml.Encode(structure)
	if err != nil {
		return nil, nil, err
	}
	markdown, chunks := officeText(structure)
	digest := sha256Hex(encoded)
	return &types.ReadResult{
		MarkdownContent: markdown,
		NativeStructure: &types.NativeStructureArtifact{
			SchemaVersion: ooxml.Contract, SourceSHA256: structure.SourceSHA256,
			RawSHA256: digest, SanitizedSHA256: digest, SanitizedJSON: encoded,
		},
	}, chunks, nil
}

func officeText(structure *ooxml.Structure) (string, []types.ParsedChunk) {
	var text strings.Builder
	var chunks []types.ParsedChunk
	offset := 0
	for i, page := range structure.Pages {
		if i > 0 {
			text.WriteString("\n\n")
			offset += 2
		}
		length := utf8.RuneCountInString(page.Text)
		if strings.TrimSpace(page.Text) != "" {
			chunks = append(chunks, types.ParsedChunk{Content: page.Text, Seq: i, Start: offset, End: offset + length})
		}
		text.WriteString(page.Text)
		offset += length
	}
	return text.String(), chunks
}

// validateOffice checks an Office native artifact: digests, canonical encoding, the full structure
// verification, the source and parser identity, and that the captured Markdown is its page text.
func validateOffice(result *types.ReadResult, sourceSHA, parserIdentitySHA string) error {
	artifact := result.NativeStructure
	if len(result.ImageRefs) != 0 || result.IsAudio || artifact.SourceSHA256 != sourceSHA ||
		artifact.RawSHA256 != artifact.SanitizedSHA256 ||
		sha256Hex(artifact.SanitizedJSON) != artifact.SanitizedSHA256 {
		return ErrUnavailable
	}
	structure, err := ooxml.Decode(artifact.SanitizedJSON)
	if err != nil {
		return ErrUnavailable
	}
	canonical, err := ooxml.Encode(structure)
	if err != nil || !bytes.Equal(canonical, artifact.SanitizedJSON) ||
		structure.SourceSHA256 != sourceSHA || structure.ParserIdentitySHA256 != parserIdentitySHA {
		return ErrUnavailable
	}
	if markdown, _ := officeText(structure); markdown != result.MarkdownContent {
		return ErrUnavailable
	}
	return nil
}
