package release

import (
	"crypto/sha256"
	"encoding/hex"
	"sort"
	"strings"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

// QuoteDigest is Evidence.quote_sha256 as the Harness defines it: sha256 of
// "".join(unicodedata.normalize("NFKC", quote).split()) — the NFKC quote with every
// character Python's str.split() treats as whitespace removed.
func QuoteDigest(quote string) string {
	var kept strings.Builder
	for _, r := range pythonNFKC(quote) {
		if pythonSpace(r) {
			continue
		}
		kept.WriteRune(r)
	}
	sum := sha256.Sum256([]byte(kept.String()))
	return hex.EncodeToString(sum[:])
}

// pythonSpace is str.isspace: Go's unicode.IsSpace lacks U+001C..U+001F, which Python
// counts as separators.
func pythonSpace(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) }

// pythonNFKC normalizes exactly like Python's unicodedata.normalize("NFKC", s): compatibility
// decomposition, canonical ordering of every run of non-starters however long, then canonical
// composition (UAX #15). x/text's norm forms follow the Stream-Safe Text Format and insert
// U+034F after 30 non-starters, which Python does not, so the forms are applied only to single
// characters and character pairs, which never reach that limit.
func pythonNFKC(s string) []rune {
	decomposed := make([]rune, 0, len(s))
	for _, r := range s {
		decomposed = append(decomposed, []rune(norm.NFKD.String(string(r)))...)
	}
	for start := 0; start < len(decomposed); {
		if combiningClass(decomposed[start]) == 0 {
			start++
			continue
		}
		end := start
		for end < len(decomposed) && combiningClass(decomposed[end]) != 0 {
			end++
		}
		run := decomposed[start:end]
		sort.SliceStable(run, func(i, j int) bool { return combiningClass(run[i]) < combiningClass(run[j]) })
		start = end
	}
	composed := make([]rune, 0, len(decomposed))
	starter, lastClass := -1, uint8(0)
	for _, r := range decomposed {
		class := combiningClass(r)
		// r is blocked from the starter when a character between them is a starter or has
		// a combining class at least as high (canonical order puts the highest last).
		blocked := len(composed)-1 > starter && (lastClass == 0 || lastClass >= class)
		if starter >= 0 && !blocked {
			if pair, ok := primaryComposite(composed[starter], r); ok {
				composed[starter] = pair
				continue
			}
		}
		composed = append(composed, r)
		lastClass = class
		if class == 0 {
			starter = len(composed) - 1
		}
	}
	return composed
}

func combiningClass(r rune) uint8 { return norm.NFD.PropertiesString(string(r)).CCC() }

// primaryComposite composes a starter with one following character, honouring the
// composition exclusions; NFC of an already decomposed pair is the composite or the pair.
func primaryComposite(starter, next rune) (rune, bool) {
	out := []rune(norm.NFC.String(string([]rune{starter, next})))
	if len(out) != 1 {
		return 0, false
	}
	return out[0], true
}
