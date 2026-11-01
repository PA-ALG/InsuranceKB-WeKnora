package knowledge

import (
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

// The question intents a navigation may publish terms for (Spec §4.1).
const (
	intentSales   = "sales"
	intentService = "service"
)

// questionIntent reads only the navigation's published intent terms, matched like question_terms.
// A question matching both intents, or neither, has none and is not narrowed by type.
func (index *releaseIndex) questionIntent(termQuestion string) string {
	if index.navigation == nil {
		return ""
	}
	matched := ""
	for _, intent := range []string{intentSales, intentService} {
		for _, group := range index.navigation.QuestionIntents[intent] {
			if containsQuestionTerms(termQuestion, normalizedQuestionGroup(group)) {
				if matched != "" {
					return ""
				}
				matched = intent
				break
			}
		}
	}
	return matched
}

// forSale narrows a sales comparison over every product to versions that may be on sale on the
// read's day. Unknown status stays, labelled, so that an unmatched product does not vanish.
func forSale(entities []indexedEntity) []indexedEntity {
	out := make([]indexedEntity, 0, len(entities))
	for _, entity := range entities {
		if entity.Status != SaleDiscontinued && entity.Status != SaleNotYet {
			out = append(out, entity)
		}
	}
	return out
}

// heldVersions keeps, among the named versions of one product, those sold within the purchase
// date the question gives (Spec §4.2). Versions of one product share their name or are linked by
// supersedes. When none of them was sold then, all stay: their labels let the model ask.
func heldVersions(products []indexedEntity, question string) []indexedEntity {
	first, last, ok := purchaseSpan(question)
	if !ok || len(products) < 2 {
		return products
	}
	parent := make([]int, len(products))
	root := func(i int) int {
		for parent[i] != i {
			i = parent[i]
		}
		return i
	}
	for i := range products {
		parent[i] = i
		for j := 0; j < i; j++ {
			if sameProduct(products[i].Entity, products[j].Entity) {
				parent[root(j)] = root(i)
			}
		}
	}
	sold := map[int]bool{}
	for i, product := range products {
		if !soldOutside(product.Lifecycle, first, last) {
			sold[root(i)] = true
		}
	}
	out := make([]indexedEntity, 0, len(products))
	for i, product := range products {
		if !sold[root(i)] || !soldOutside(product.Lifecycle, first, last) {
			out = append(out, product)
		}
	}
	return out
}

func sameProduct(a, b Entity) bool {
	return contains(a.Predecessors, b.EntityID) || contains(b.Predecessors, a.EntityID) ||
		normalizeProductText(a.Name) == normalizeProductText(b.Name)
}

// soldOutside reports whether a known sale period [start, end) excludes every day of [first, last];
// unknown dates exclude nothing.
func soldOutside(lifecycle *Lifecycle, first, last string) bool {
	return lifecycle != nil && (lifecycle.SaleStart != "" && lifecycle.SaleStart > last ||
		lifecycle.SaleEnd != "" && lifecycle.SaleEnd <= first)
}

// A date as YYYY年M月D日 (or 号), YYYY年M月, YYYY年, YYYY-MM-DD or YYYY/M/D. These are calendar
// notations, not domain vocabulary; wholeToken rejects one that is part of a longer number or code.
var purchaseDate = regexp.MustCompile(
	`(\d{4})(?:-(\d{1,2})-(\d{1,2})|/(\d{1,2})/(\d{1,2})|年(?:(\d{1,2})月(?:(\d{1,2})[日号])?)?)`)

// purchaseSpan is the first valid date of a normalized question as its first and last day.
func purchaseSpan(question string) (first, last string, ok bool) {
	for _, index := range purchaseDate.FindAllStringSubmatchIndex(question, -1) {
		if !wholeToken(question, index[0], index[1]) {
			continue
		}
		group := func(i int) string {
			if index[2*i] < 0 {
				return ""
			}
			return question[index[2*i]:index[2*i+1]]
		}
		year, month, day := group(1), group(2)+group(4)+group(6), group(3)+group(5)+group(7)
		switch {
		case month == "":
			start, err := time.Parse("2006", year)
			if err == nil {
				return start.Format(dateLayout), start.AddDate(1, 0, -1).Format(dateLayout), true
			}
		case day == "":
			start, err := time.Parse("2006-1", year+"-"+month)
			if err == nil {
				return start.Format(dateLayout), start.AddDate(0, 1, -1).Format(dateLayout), true
			}
		default:
			date, err := time.Parse("2006-1-2", year+"-"+month+"-"+day)
			if err == nil {
				return date.Format(dateLayout), date.Format(dateLayout), true
			}
		}
	}
	return "", "", false
}

// wholeToken reports whether text[start:end] stands alone: an ASCII letter or digit next to it, or a
// joiner followed by one ("2023-06-18-0001", "no.2023-06-18"), makes it part of a longer code
// such as a policy number, which is no purchase date (#517 R1).
func wholeToken(text string, start, end int) bool {
	before, size := utf8.DecodeLastRuneInString(text[:start])
	after, next := utf8.DecodeRuneInString(text[end:])
	return !continues(before, lastRune(text[:start-size])) && !continues(after, firstRune(text[end+next:]))
}

// continues reports whether r, with beyond on its far side, carries a code on past the date.
func continues(r, beyond rune) bool { return codeRune(r) || joiner(r) && codeRune(beyond) }

func codeRune(r rune) bool {
	return r >= '0' && r <= '9' || r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z'
}

func joiner(r rune) bool { return r < utf8.RuneSelf && strings.ContainsRune("-/._:", r) }

func firstRune(text string) rune {
	r, _ := utf8.DecodeRuneInString(text)
	return r
}

func lastRune(text string) rune {
	r, _ := utf8.DecodeLastRuneInString(text)
	return r
}
