// S7d-2c-3b acceptance (protected, written by Claude): the pipeline reads the parser identity of a
// native structure through this package (Spec docs/design/slices/S7d-2c-3b-首次解析采集与旧服务解耦.md §4).
// RED until S7d-2c-3b: ParserIdentitySHA256 is not exported.
package capture_test

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestParserIdentityIsReadFromTheNativeStructure(t *testing.T) {
	in, _ := load(t)
	got, err := capture.ParserIdentitySHA256(result(in))
	require.NoError(t, err)
	require.True(t, capture.ValidSHA256(got))
	require.NoError(t, capture.ValidateNative(result(in), in.Identity.SourceSHA256, got))

	_, err = capture.ParserIdentitySHA256(&types.ReadResult{MarkdownContent: in.Markdown})
	require.ErrorIs(t, err, capture.ErrUnavailable)
	broken := *in.Native
	broken.SanitizedJSON = []byte("{")
	_, err = capture.ParserIdentitySHA256(&types.ReadResult{MarkdownContent: in.Markdown, NativeStructure: &broken})
	require.ErrorIs(t, err, capture.ErrUnavailable)
}
