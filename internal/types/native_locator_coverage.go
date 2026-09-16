package types

import "unicode"

const NativePartialLocatorContract = "builtin-pdfium-native-locators.v2"

// NativeUnavailableRange is an explicit absence of geometry, never a rectangle.
// Fields follow canonical JSON key order. Legacy pages omit the entire list.
type NativeUnavailableRange struct {
	GlobalCodepointEnd   int    `json:"global_codepoint_end"`
	GlobalCodepointStart int    `json:"global_codepoint_start"`
	Reason               string `json:"reason"`
}

func ValidNativeLocatorIdentity(contract, producer string) bool {
	return contract == "builtin-pdfium-native-locators.v1" && producer == "weknora.docreader.builtin-pdfium-charbox.v1" ||
		contract == NativePartialLocatorContract && producer == "weknora.docreader.builtin-pdfium-charbox.v2"
}

// ValidateNativeLocatorCoverage requires one disposition per non-whitespace
// codepoint. Both transport admission and persisted evidence indexing use it.
// Coordinates must have been validated by the caller; no absent box is invented.
func ValidateNativeLocatorCoverage[T any](contract string, text []rune, start int, positions map[int]T, gaps []NativeUnavailableRange) bool {
	if contract != "builtin-pdfium-native-locators.v1" && contract != NativePartialLocatorContract {
		return false
	}
	if len(gaps) > 0 && contract != NativePartialLocatorContract {
		return false
	}
	unavailable := 0
	last := start
	for _, gap := range gaps {
		switch gap.Reason {
		case "bbox_invalid", "bbox_unavailable", "character_mapping_unavailable", "page_rotation_unsupported":
		default:
			return false
		}
		if gap.GlobalCodepointStart < last || gap.GlobalCodepointStart < start || gap.GlobalCodepointEnd <= gap.GlobalCodepointStart || gap.GlobalCodepointEnd > start+len(text) {
			return false
		}
		for pos := gap.GlobalCodepointStart; pos < gap.GlobalCodepointEnd; pos++ {
			_, located := positions[pos]
			if unicode.IsSpace(text[pos-start]) || located {
				return false
			}
			unavailable++
		}
		last = gap.GlobalCodepointEnd
	}
	visible, locatedCount := 0, 0
	for i, ch := range text {
		_, located := positions[start+i]
		if unicode.IsSpace(ch) {
			if located {
				return false
			}
			continue
		}
		visible++
		if located {
			locatedCount++
		}
	}
	return locatedCount == len(positions) && visible == locatedCount+unavailable
}
