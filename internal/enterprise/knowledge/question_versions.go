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

// questionScope is a question's intent and the products it names. A service question's named
// versions are narrowed to those sold on its purchase date (PV-4b §4.2, PV-5 §4.2). Published
// fields and raw retrieval read the same scope.
func (index *releaseIndex) questionScope(question string) (intent string, products []indexedEntity) {
	question = normalize(question)
	products = index.questionProducts(question)
	intent = index.questionIntent(normalizeQuestionTerm(question))
	if intent == intentService {
		products = index.heldVersions(products, question)
	}
	return intent, products
}

// notOnSale holds for a version known to be discontinued or not yet on sale on the read's day.
func notOnSale(entity indexedEntity) bool {
	return entity.Status == SaleDiscontinued || entity.Status == SaleNotYet
}

// forSale narrows a sales comparison over every product to versions that may be on sale on the
// read's day. Unknown status stays, labelled, so that an unmatched product does not vanish.
func forSale(entities []indexedEntity) []indexedEntity {
	out := make([]indexedEntity, 0, len(entities))
	for _, entity := range entities {
		if !notOnSale(entity) {
			out = append(out, entity)
		}
	}
	return out
}

// heldVersions keeps, among the versions of one product, those sold within the purchase date the
// question gives (Spec §4.2). Versions of one product share their name or are linked by supersedes;
// the candidates are the named versions and every version linked to one of them (PV-5 §4.2), as a
// question names a product line by one year's name. When none of a group was sold then, only its
// named versions stay: their labels let the model ask.
func (index *releaseIndex) heldVersions(named []indexedEntity, question string) []indexedEntity {
	first, last, ok := purchaseSpan(question)
	if !ok {
		return named
	}
	products := index.withLinkedVersions(named)
	if len(products) < 2 {
		return named
	}
	asked := map[string]bool{}
	for _, product := range named {
		asked[product.EntityID] = true
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
		if sold[root(i)] && !soldOutside(product.Lifecycle, first, last) || !sold[root(i)] && asked[product.EntityID] {
			out = append(out, product)
		}
	}
	return out
}

// withLinkedVersions adds to the named versions every product version the release links to one of
// them by supersedes, in either direction and transitively, in navigation order.
func (index *releaseIndex) withLinkedVersions(named []indexedEntity) []indexedEntity {
	reached := map[string]bool{}
	queue := []string{}
	for _, product := range named {
		reached[product.EntityID] = true
		queue = append(queue, product.EntityID)
	}
	for len(queue) > 0 {
		entity := index.entities[index.entityByID[queue[0]]].Entity
		queue = queue[1:]
		for _, id := range append(append([]string{}, entity.Predecessors...), entity.Successors...) {
			if !reached[id] {
				reached[id] = true
				queue = append(queue, id)
			}
		}
	}
	out := []indexedEntity{}
	for _, entity := range index.productEntities() {
		if reached[entity.EntityID] {
			out = append(out, entity)
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
