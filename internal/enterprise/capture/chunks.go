package capture

import (
	"strings"

	"github.com/Tencent/WeKnora/internal/infrastructure/chunker"
	"github.com/Tencent/WeKnora/internal/types"
)

// ExactChunks makes every chunk's content the exact Markdown text of its range. Existing chunkers
// may prepend a table header; that header is context, never source, so it moves to ContextHeader.
// Any other mismatch between content and range fails.
func ExactChunks(markdown string, chunks []types.ParsedChunk) ([]types.ParsedChunk, error) {
	result := append([]types.ParsedChunk(nil), chunks...)
	runes := []rune(markdown)
	for i := range result {
		c := &result[i]
		if c.Start < 0 || c.End <= c.Start || c.End > len(runes) {
			return nil, ErrUnavailable
		}
		exact := string(runes[c.Start:c.End])
		if c.Content != exact {
			if !strings.HasSuffix(c.Content, exact) {
				return nil, ErrUnavailable
			}
			header := strings.TrimSuffix(c.Content, exact)
			if c.ContextHeader != "" {
				c.ContextHeader += "\n\n"
			}
			c.ContextHeader += header
			c.Content = exact
		}
	}
	return result, nil
}

// SplitParentChild is the parent-child split for captured parses. It normalizes each parent before
// splitting its children: the generic chunker can add a contextual table header, and splitting that
// synthetic prefix first would shift every child coordinate relative to the original document.
func SplitParentChild(text string, parentCfg, childCfg chunker.SplitterConfig) (chunker.ParentChildResult, error) {
	result := chunker.ParentChildResult{}
	parents := chunker.Split(text, parentCfg)
	seq := 0
	for _, p := range parents {
		exact, err := ExactChunks(text, []types.ParsedChunk{
			{Content: p.Content, ContextHeader: p.ContextHeader, Start: p.Start, End: p.End, Seq: p.Seq},
		})
		if err != nil {
			return result, err
		}
		p.Content = exact[0].Content
		p.ContextHeader = exact[0].ContextHeader
		children := chunker.Split(p.Content, childCfg)
		parentIndex := -1
		if len(children) > 1 || (len(children) == 1 && children[0].Content != p.Content) {
			parentIndex = len(result.Parents)
			result.Parents = append(result.Parents, p)
		}
		for _, c := range children {
			exact, err := ExactChunks(p.Content, []types.ParsedChunk{
				{Content: c.Content, ContextHeader: c.ContextHeader, Start: c.Start, End: c.End, Seq: c.Seq},
			})
			if err != nil {
				return result, err
			}
			c.Content = exact[0].Content
			c.ContextHeader = exact[0].ContextHeader
			if p.ContextHeader != "" {
				if c.ContextHeader != "" {
					c.ContextHeader = p.ContextHeader + "\n\n" + c.ContextHeader
				} else {
					c.ContextHeader = p.ContextHeader
				}
			}
			c.Start += p.Start
			c.End += p.Start
			c.Seq = seq
			seq++
			result.Children = append(result.Children, chunker.ChildChunk{Chunk: c, ParentIndex: parentIndex})
		}
	}
	for i := range result.Parents {
		result.Parents[i].Seq = i
	}
	for i := range result.Children {
		result.Children[i].Seq = len(result.Parents) + i
	}
	return result, nil
}
