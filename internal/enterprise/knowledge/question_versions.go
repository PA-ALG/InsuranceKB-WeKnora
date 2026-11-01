package knowledge

import (
	"regexp"
	"time"
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

// A date as YYYY年M月D日 (or 号), YYYY年M月, YYYY年, YYYY-MM-DD or YYYY/M/D, not inside a longer
// number. These are calendar notations, not domain vocabulary.
var purchaseDate = regexp.MustCompile(
	`(?:^|\D)(\d{4})(?:-(\d{1,2})-(\d{1,2})|/(\d{1,2})/(\d{1,2})|年(?:(\d{1,2})月(?:(\d{1,2})[日号])?)?)`)

// purchaseSpan is the first valid date of a normalized question as its first and last day.
func purchaseSpan(question string) (first, last string, ok bool) {
	for _, match := range purchaseDate.FindAllStringSubmatch(question, -1) {
		month, day := match[2]+match[4]+match[6], match[3]+match[5]+match[7]
		switch {
		case month == "":
			start, err := time.Parse("2006", match[1])
			if err == nil {
				return start.Format(dateLayout), start.AddDate(1, 0, -1).Format(dateLayout), true
			}
		case day == "":
			start, err := time.Parse("2006-1", match[1]+"-"+month)
			if err == nil {
				return start.Format(dateLayout), start.AddDate(0, 1, -1).Format(dateLayout), true
			}
		default:
			date, err := time.Parse("2006-1-2", match[1]+"-"+month+"-"+day)
			if err == nil {
				return date.Format(dateLayout), date.Format(dateLayout), true
			}
		}
	}
	return "", "", false
}
