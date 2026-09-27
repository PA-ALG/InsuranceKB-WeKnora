// Local, provider-free preparation: reuse the production splitter on saved native captures.
package main

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/infrastructure/chunker"
)

type Capture struct {
	MaterialID  string `json:"material_id"`
	Path        string `json:"path"`
	FileSHA     string `json:"file_sha256"`
	CaptureSHA  string `json:"capture_file_sha256"`
	MarkdownSHA string `json:"markdown_sha256"`
}
type Entry struct {
	ID   string `json:"inventory_id"`
	Path string `json:"path"`
	SHA  string `json:"file_sha256"`
}

func check(ok bool, why string) {
	if !ok {
		panic(why)
	}
}
func read(path string) []byte {
	b, e := os.ReadFile(path)
	if e != nil {
		panic(e)
	}
	return b
}
func sha(b []byte) string { d := sha256.Sum256(b); return hex.EncodeToString(d[:]) }
func encode(v any) []byte {
	var b bytes.Buffer
	e := json.NewEncoder(&b)
	e.SetEscapeHTML(false)
	if err := e.Encode(v); err != nil {
		panic(err)
	}
	return bytes.TrimSuffix(b.Bytes(), []byte("\n"))
}
func main() {
	check(len(os.Args) == 3, "usage: go run helper.go ROOT OUTPUT_DIR")
	root, out := os.Args[1], os.Args[2]
	if err := os.MkdirAll(out, 0700); err != nil {
		panic(err)
	}
	inventoryPath := filepath.Join(root, "docs/insurance-kb/evidence/830-g3/native-capture-inventory.json")
	corpusPath := filepath.Join(root, "docs/insurance-kb/evidence/830-g3/corpus-files-v4.json")
	var inv struct {
		Documents []Capture `json:"documents"`
	}
	if err := json.Unmarshal(read(inventoryPath), &inv); err != nil {
		panic(err)
	}
	var corpus struct {
		Entries []Entry `json:"entries"`
	}
	if err := json.Unmarshal(read(corpusPath), &corpus); err != nil {
		panic(err)
	}
	entries := map[string]Entry{}
	for _, e := range corpus.Entries {
		check(entries[e.ID].ID == "", "duplicate corpus id")
		entries[e.ID] = e
	}
	check(len(inv.Documents) == 11, "expected eleven saved captures")
	cfg := chunker.SplitterConfig{ChunkSize: 2048, ChunkOverlap: 80, Separators: []string{"\n\n", "\n", "。"}, Strategy: chunker.StrategyLegacy, TokenLimit: 0, Languages: nil}
	var documents []any
	seen := map[string]bool{}
	total := 0
	for _, c := range inv.Documents {
		check(!seen[c.MaterialID], "duplicate capture")
		seen[c.MaterialID] = true
		e, ok := entries[c.MaterialID]
		check(ok && e.SHA == c.FileSHA, "capture source mismatch")
		check(sha(read(filepath.Join(root, e.Path))) == e.SHA, "source drift")
		raw := read(filepath.Join(root, c.Path))
		check(sha(raw) == c.CaptureSHA, "capture drift")
		zr, err := gzip.NewReader(bytes.NewReader(raw))
		if err != nil {
			panic(err)
		}
		data, err := io.ReadAll(io.LimitReader(zr, 64<<20))
		if err != nil {
			panic(err)
		}
		if err = zr.Close(); err != nil {
			panic(err)
		}
		var capture struct {
			Markdown string `json:"markdown"`
		}
		if err = json.Unmarshal(data, &capture); err != nil {
			panic(err)
		}
		text := capture.Markdown
		check(sha([]byte(text)) == c.MarkdownSHA, "markdown drift")
		check(utf8.ValidString(text) && !strings.ContainsRune(text, 0), "invalid UTF8/NUL")
		lower := strings.ToLower(text)
		check(!strings.Contains(text, "![") && !strings.Contains(lower, "<img") && !strings.Contains(lower, "base64,") && !strings.Contains(lower, "data:image"), "image/sanitizer not identity")
		title := filepath.Base(e.Path)
		check(strings.TrimSpace(title) == title && title != "", "invalid title")
		chunks := chunker.Split(text, cfg)
		sort.Slice(chunks, func(i, j int) bool { return chunks[i].Seq < chunks[j].Seq })
		var records []any
		var inputs []string
		prev := -1
		for _, ch := range chunks {
			check(ch.Seq > prev, "unordered splitter output")
			prev = ch.Seq
			if strings.TrimSpace(ch.Content) == "" {
				continue
			}
			check(ch.ContextHeader == "", "unexpected context header")
			input := strings.TrimSpace(title) + "\n" + ch.EmbeddingContent()
			check(utf8.RuneCountInString(input) <= 20000 && !strings.Contains(input, "base64,"), "sanitizer would change input")
			records = append(records, map[string]any{"seq": ch.Seq, "start": ch.Start, "end": ch.End, "content_sha256": sha([]byte(ch.Content)), "context_header_sha256": sha([]byte(ch.ContextHeader)), "embedding_input_sha256": sha([]byte(input)), "input_utf8_bytes": len([]byte(input))})
			inputs = append(inputs, input)
		}
		check(len(inputs) > 0 && len(inputs) <= 100, "whole-document request outside frozen batch100")
		payload := encode(map[string]any{"model": "qwen3.7-text-embedding", "input": inputs})
		path := filepath.Join(out, c.MaterialID+"-embedding-input.json")
		check(!fileExists(path), "refuse overwriting existing preparation")
		if err = os.WriteFile(path, payload, 0600); err != nil {
			panic(err)
		}
		documents = append(documents, map[string]any{"material_id": c.MaterialID, "source_sha256": e.SHA, "capture_file_sha256": c.CaptureSHA, "markdown_sha256": c.MarkdownSHA, "upload_file_name": title, "chunk_count": len(inputs), "chunks": records, "ordered_inputs_json_sha256": sha(encode(inputs)), "prepared_model_input_sha256": sha(payload), "prepared_model_input_path": path})
		total += len(inputs)
	}
	result := map[string]any{"contract": "830-g3-offline-embedding-inputs.v1", "status": "PREPARED_NOT_SENT", "documents": documents, "input_count": total, "expected_request_count": len(documents), "batch_embed_size": 100, "provider_calls": 0, "knowledge_uploads": 0, "kb_readback_requirements": []string{"token_limit=0", "languages=[]", "summary_model_id empty", "wiki_enabled=false"}, "note": "Prepared model/input bodies only. Actual transport optional parameters must be frozen independently before execution; no HTTP request has occurred."}
	dest := filepath.Join(out, "embedding-whitelist.json")
	check(!fileExists(dest), "refuse overwriting whitelist")
	if err := os.WriteFile(dest, encode(result), 0600); err != nil {
		panic(err)
	}
	fmt.Printf("Prepared %d documents, %d inputs; provider calls 0\n", len(documents), total)
}
func fileExists(path string) bool { _, err := os.Stat(path); return !os.IsNotExist(err) }
