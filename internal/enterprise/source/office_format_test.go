package source_test

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/source"
)

// A stored Office structure names its format by the frozen literal; an input alias of the same format
// is an integrity failure. The artifact carries the structure's own source digest, so the format is the
// only thing that differs from the accepted control.
func TestAnOfficeCaptureWithANonCanonicalFormatFailsClosed(t *testing.T) {
	load := func(format string) error {
		structure := bookFixture()
		structure.Format = format
		native, err := json.Marshal(structure)
		require.NoError(t, err)
		artifact := &source.Artifact{
			KnowledgeID: "k-1", ParseAttempt: 2, FileName: "费率.xlsx", FileSHA256: structure.SourceSHA256,
			ParserIdentitySHA256: sha(officeExtractor), Markdown: "#", NativeJSON: native,
		}
		_, err = source.NewService(&store{artifact: artifact}).Pages(context.Background(), scope, "k-1", 2)
		return err
	}
	require.NoError(t, load("xlsx"), "positive control")
	for _, format := range []string{"XLSX", ".xlsx", " xlsx", ".docx", "PPTX"} {
		t.Run(fmt.Sprintf("%q", format), func(t *testing.T) {
			require.Equal(t, "PARSE_ARTIFACT_INTEGRITY", code(t, load(format)))
		})
	}
}
