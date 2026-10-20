package mcptools

import (
	"bytes"
	"encoding/json"
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

func nonnegativeInteger(raw json.RawMessage) (int, bool) {
	raw = bytes.TrimSpace(raw)
	if len(raw) == 0 || (raw[0] != '-' && (raw[0] < '0' || raw[0] > '9')) {
		return 0, false
	}
	var number json.Number
	if json.Unmarshal(raw, &number) != nil {
		return 0, false
	}
	// Work on decimal digits, never floating-point rounding or a huge power of
	// ten. A client-controlled exponent must not cause large allocations.
	mantissa, exponent, hasExponent := strings.Cut(strings.ToLower(number.String()), "e")
	negative := strings.HasPrefix(mantissa, "-")
	mantissa = strings.TrimPrefix(mantissa, "-")
	fraction := 0
	if dot := strings.IndexByte(mantissa, '.'); dot >= 0 {
		fraction = len(mantissa) - dot - 1
	}
	digits := strings.TrimLeft(strings.ReplaceAll(mantissa, ".", ""), "0")
	if digits == "" {
		return 0, true // includes negative zero, decimal zeros, and zero exponents
	}
	if negative {
		return 0, false
	}
	significant := strings.TrimRight(digits, "0")
	fraction -= len(digits) - len(significant)
	var exp int64
	if hasExponent {
		var err error
		exp, err = strconv.ParseInt(exponent, 10, 64)
		if err != nil {
			return 0, false
		}
	}
	// An integer needs a nonnegative scale and at most 19 decimal digits.
	// Compare before subtraction so an extreme exponent cannot overflow.
	if exp < int64(fraction) || exp > int64(fraction)+19 || len(significant) > 19 {
		return 0, false
	}
	scale := int(exp - int64(fraction))
	if len(significant)+scale > 19 {
		return 0, false
	}
	value, err := strconv.ParseInt(significant+strings.Repeat("0", scale), 10, strconv.IntSize)
	return int(value), err == nil
}

func invalidArguments() error {
	return &release.Error{Code: release.ErrorInvalidRequest}
}
