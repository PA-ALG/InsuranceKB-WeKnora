package mcptools

import (
	"bytes"
	"encoding/json"
	"regexp"
	"strconv"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

type arguments map[string]json.RawMessage

func parseArguments(value any, schema argumentSchema) (arguments, error) {
	if value == nil && len(schema.Properties) == 0 {
		value = map[string]any{}
	}
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, invalidArguments()
	}
	var args arguments
	if err := json.Unmarshal(raw, &args); err != nil || args == nil {
		return nil, invalidArguments()
	}
	for name, raw := range args {
		prop, ok := schema.Properties[name]
		if !ok || bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
			return nil, invalidArguments()
		}
		switch prop.Type {
		case "string":
			var value string
			if json.Unmarshal(raw, &value) != nil {
				return nil, invalidArguments()
			}
		case "array":
			var values []json.RawMessage
			if json.Unmarshal(raw, &values) != nil || values == nil {
				return nil, invalidArguments()
			}
			for _, item := range values {
				var value string
				if bytes.Equal(item, []byte("null")) || json.Unmarshal(item, &value) != nil {
					return nil, invalidArguments()
				}
			}
		case "integer":
			if _, ok := nonnegativeInteger(raw); !ok {
				return nil, invalidArguments()
			}
		default:
			return nil, invalidArguments()
		}
	}
	for _, name := range schema.Required {
		if _, ok := args[name]; !ok {
			return nil, invalidArguments()
		}
		if (name == "space_id" || name == "release_id" || name == "member") &&
			strings.TrimSpace(args.string(name)) == "" {
			return nil, invalidArguments()
		}
	}
	if _, exists := args["release_id"]; exists {
		id := strings.TrimSpace(args.string("release_id"))
		if id == "" || strings.EqualFold(id, "active") {
			return nil, invalidArguments()
		}
	}
	return args, nil
}

func (args arguments) string(name string) string {
	var value string
	_ = json.Unmarshal(args[name], &value)
	return value
}

// parseArguments reserializes the SDK's arguments; mcp-go v1 keeps the
// literal JSON number, so only plain non-negative integer spellings match.
var evidenceIndexPattern = regexp.MustCompile(`^(0|[1-9][0-9]{0,5})$`)

func nonnegativeInteger(raw json.RawMessage) (int, bool) {
	if !evidenceIndexPattern.Match(raw) {
		return 0, false
	}
	value, err := strconv.Atoi(string(raw))
	return value, err == nil
}

func invalidArguments() error {
	return &release.Error{Code: release.ErrorInvalidRequest}
}
