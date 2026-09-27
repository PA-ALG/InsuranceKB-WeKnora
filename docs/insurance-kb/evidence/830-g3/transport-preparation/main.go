// Offline transport serialization using the actual exported request DTO; no model calls.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/Tencent/WeKnora/internal/models/embedding"
)

func main() {
	if len(os.Args) != 3 {
		panic("expected prepared directory and output directory")
	}
	inputDir, outDir := os.Args[1], os.Args[2]
	if err := os.MkdirAll(outDir, 0700); err != nil {
		panic(err)
	}
	input, err := os.ReadFile(filepath.Join(inputDir, "embedding-whitelist.json"))
	if err != nil {
		panic(err)
	}
	var w struct {
		Documents []struct {
			ID            string `json:"material_id"`
			SourceSHA     string `json:"source_sha256"`
			Path          string `json:"prepared_model_input_path"`
			ProjectionSHA string `json:"prepared_model_input_sha256"`
		} `json:"documents"`
	}
	if err = json.Unmarshal(input, &w); err != nil {
		panic(err)
	}
	if len(w.Documents) != 11 {
		panic("expected11documents")
	}
	var records []map[string]any
	for _, d := range w.Documents {
		raw, err := os.ReadFile(d.Path)
		if err != nil {
			panic(err)
		}
		if digest(raw) != d.ProjectionSHA {
			panic("projection drift")
		}
		var p struct {
			Model string   `json:"model"`
			Input []string `json:"input"`
		}
		if err = json.Unmarshal(raw, &p); err != nil {
			panic(err)
		}
		if p.Model != "qwen3.7-text-embedding" || len(p.Input) < 1 || len(p.Input) > 100 {
			panic("projection shape")
		}
		// Current model readback: truncate=0 is normalized by NewOpenAIEmbedder to511;
		// dimension=1024 is not sent because supports_dimension_override=false.
		body, err := json.Marshal(embedding.OpenAIEmbedRequest{Model: p.Model, Input: p.Input, EncodingFormat: "float", TruncatePromptTokens: 511})
		if err != nil {
			panic(err)
		}
		path := filepath.Join(outDir, d.ID+"-request.json")
		if _, err = os.Stat(path); !os.IsNotExist(err) {
			panic("refuse existing request")
		}
		if err = os.WriteFile(path, body, 0600); err != nil {
			panic(err)
		}
		records = append(records, map[string]any{"material_id": d.ID, "source_sha256": d.SourceSHA, "request_sha256": digest(body), "body_bytes": len(body), "input_count": len(p.Input), "path": path})
	}
	manifest := map[string]any{"contract": "830-g3-prepared-embedding-transport.v1", "status": "PREPARED_NOT_SENT", "upstream": "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings", "model": "qwen3.7-text-embedding", "encoding_format": "float", "truncate_prompt_tokens": 511, "dimensions_sent": false, "batch_embed_size": 100, "requests": records, "provider_calls": 0, "note": "Exact offline Go DTO serialization. Actual proxy must compare inbound body SHA before forwarding; generation is not evidence of an actual request."}
	raw, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		panic(err)
	}
	dest := filepath.Join(outDir, "transport-manifest.json")
	if _, err = os.Stat(dest); !os.IsNotExist(err) {
		panic("refuse existing manifest")
	}
	if err = os.WriteFile(dest, raw, 0600); err != nil {
		panic(err)
	}
	fmt.Printf("Prepared %d exact transport bodies; HTTP calls0\n", len(records))
}
func digest(b []byte) string { v := sha256.Sum256(b); return hex.EncodeToString(v[:]) }
