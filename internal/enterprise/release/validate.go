package release

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// No fallback loader: only schemas explicitly supplied by the caller can be
// resolved. In particular, a schema $ref cannot read local files or fetch URLs.
type suppliedSchemasOnly struct{}

func (suppliedSchemasOnly) Load(string) (any, error) {
	return nil, errors.New("schema reference was not supplied")
}

func compileSchema(schemas map[string][]byte) (*jsonschema.Schema, error) {
	compiler := jsonschema.NewCompiler()
	compiler.UseLoader(suppliedSchemasOnly{})
	compiler.AssertFormat()
	names := make([]string, 0, len(schemas))
	for name := range schemas {
		names = append(names, name)
	}
	sort.Strings(names)
	root := ""
	for _, name := range names {
		doc, err := jsonschema.UnmarshalJSON(bytes.NewReader(schemas[name]))
		if err != nil {
			return nil, fmt.Errorf("decode schema: %w", err)
		}
		name = strings.TrimSuffix(name, ".schema.json")
		uri := "https://schemas.enterprise.invalid/" + name + ".schema.json"
		if obj, ok := doc.(map[string]any); ok {
			if id, ok := obj["$id"].(string); ok && id != "" {
				uri = id
			}
		}
		if err := compiler.AddResource(uri, doc); err != nil {
			return nil, fmt.Errorf("load schema: %w", err)
		}
		if name == "candidate_bundle" {
			root = uri
		}
	}
	if root == "" {
		return nil, errors.New("candidate bundle schema is required")
	}
	return compiler.Compile(root)
}

func (s *Service) validate(ctx context.Context, raw []byte) (Bundle, string, error) {
	if len(raw) > MaxBundleBytes {
		return Bundle{}, "", invalid("bundle exceeds size limit")
	}
	doc, err := strictJSON(raw)
	if err != nil {
		return Bundle{}, "", invalid(err.Error())
	}
	object, ok := doc.(map[string]any)
	if !ok || object["contract_version"] != SupportedContractVersion {
		return Bundle{}, "", invalid("unsupported /contract_version")
	}
	if s.schemaErr != nil || s.schema == nil {
		return Bundle{}, "", invalid("candidate bundle schema is unavailable")
	}
	// Schema integer/minimum checks must see exact number tokens. The frozen
	// digest contract uses float64, whose rounding must not weaken validation.
	schemaDoc, err := jsonschema.UnmarshalJSON(bytes.NewReader(raw))
	if err != nil {
		return Bundle{}, "", invalid("malformed JSON document")
	}
	if err := s.schema.Validate(schemaDoc); err != nil {
		return Bundle{}, "", invalid(schemaErrorLocation(err))
	}
	var b Bundle
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&b); err != nil {
		return Bundle{}, "", invalid("bundle fields do not match the contract")
	}
	b.RawJSON = bytes.Clone(raw)
	if err := validateMembers(b); err != nil {
		return Bundle{}, "", err
	}
	for _, m := range b.Members {
		for _, ref := range m.EvidenceRefs {
			if err := ctx.Err(); err != nil {
				return Bundle{}, "", err
			}
			if s.evidence == nil || strings.TrimSpace(ref) == "" {
				return Bundle{}, "", invalid("evidence reference cannot be resolved")
			}
			found, err := s.evidence.Resolve(ctx, ref)
			if err != nil || !found {
				return Bundle{}, "", invalid("evidence reference cannot be verified")
			}
		}
	}
	return b, canonicalDigest(doc), nil
}

func validateMembers(b Bundle) error {
	slugs := make(map[string]bool, len(b.Members))
	for i, m := range b.Members {
		var payload any
		if err := json.Unmarshal(m.Payload, &payload); err != nil || canonicalDigest(payload) != m.MemberDigest {
			return invalid(fmt.Sprintf("digest mismatch at /members/%d/member_digest", i))
		}
		if strings.TrimSpace(m.LogicalSlug) == "" || slugs[m.LogicalSlug] {
			return invalid(fmt.Sprintf("empty or repeated slug at /members/%d/logical_slug", i))
		}
		slugs[m.LogicalSlug] = true
	}
	removed := make(map[string]bool, len(b.Removals))
	for i, slug := range b.Removals {
		if strings.TrimSpace(slug) == "" || slugs[slug] || removed[slug] {
			return invalid(fmt.Sprintf("empty, repeated or overlapping removal at /removals/%d", i))
		}
		removed[slug] = true
	}
	return nil
}

// The digest contract is json.Unmarshal into any followed by json.Marshal.
// Inputs here have already been decoded as JSON; they cannot contain values
// (NaN, functions, cyclic maps) that json.Marshal cannot encode.
func canonicalDigest(value any) string {
	raw, _ := json.Marshal(value)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func schemaErrorLocation(err error) string {
	var failure *jsonschema.ValidationError
	if !errors.As(err, &failure) {
		return "schema validation failed at /"
	}
	for len(failure.Causes) > 0 {
		failure = failure.Causes[0]
	}
	parts := make([]string, len(failure.InstanceLocation))
	for i, part := range failure.InstanceLocation {
		parts[i] = strings.ReplaceAll(strings.ReplaceAll(part, "~", "~0"), "/", "~1")
	}
	return "schema validation failed at /" + strings.Join(parts, "/")
}
