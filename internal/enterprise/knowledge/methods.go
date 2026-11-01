package knowledge

import (
	"strings"
	"unicode/utf8"
)

// classMethod is the presentation profile's knowledge class of method knowledge (SK-3 Spec §1):
// training material, not product facts. The platform dispatches on this contract value only; the
// types it covers and the copy readers give it are published data.
const classMethod = "method"

// familyLabel prefixes a method's label naming a product family (SK-0 §2.2): family:<product_family.key>.
const familyLabel = "family:"

// profileFor is the profile an entity is shown with: the first whose entity_types name its type,
// otherwise the first without entity_types whose labels meet the entity's.
func (index *releaseIndex) profileFor(kind string, labels []string) *profilePayload {
	if kind != "" {
		for i := range index.profiles {
			if contains(index.profiles[i].Types, kind) {
				return &index.profiles[i]
			}
		}
	}
	for i := range index.profiles {
		if len(index.profiles[i].Types) == 0 && intersects(index.profiles[i].Labels, labels) {
			return &index.profiles[i]
		}
	}
	return nil
}

// markMethods flags the entities a method-knowledge profile serves.
func (index *releaseIndex) markMethods() {
	for i := range index.entities {
		entity := &index.entities[i]
		profile := index.profileFor(entity.kind, entity.Labels)
		entity.Method = profile != nil && profile.Class == classMethod && contains(profile.Types, entity.kind)
	}
}

// methodNote is the copy a method's field text opens with: the profile's reading note and the
// sentence its notices give the entity's notice flag.
func (index *releaseIndex) methodNote(entity indexedEntity) string {
	profile := index.profileFor(entity.kind, entity.Labels)
	if profile == nil {
		return ""
	}
	return profile.ReadingNote + profile.Notices[entity.Notice]
}

// alignedItems is a method list value whose items each have the evidence at their position
// (SK-2 §4.3); any other value has no items and is shown as a whole.
func alignedItems(value any, evidence int) []string {
	list, ok := value.([]any)
	if !ok || len(list) == 0 || len(list) != evidence {
		return nil
	}
	items := make([]string, 0, len(list))
	for _, item := range list {
		text, ok := item.(string)
		if !ok || strings.TrimFunc(text, browserWhitespace) == "" {
			return nil
		}
		items = append(items, text)
	}
	return items
}

// productEntities are the entries in navigation order that are not method knowledge: only they
// are named as products, own raw passages or answer product-field questions.
func (index *releaseIndex) productEntities() []indexedEntity {
	out := []indexedEntity{}
	for _, entity := range index.orderedEntities() {
		if !entity.Method {
			out = append(out, entity)
		}
	}
	return out
}

func (index *releaseIndex) methodEntities() []indexedEntity {
	out := []indexedEntity{}
	for _, entity := range index.orderedEntities() {
		if entity.Method {
			out = append(out, entity)
		}
	}
	return out
}

// relatedMethod reports whether a method serves a product: its labels name the product's family,
// or share one of the product's labels (SK-3 §5.4).
func relatedMethod(method, product Entity) bool {
	if product.Family != nil && contains(method.Labels, familyLabel+product.Family.Key) {
		return true
	}
	return intersects(method.Labels, product.Labels)
}

// entityLine of a method for knowledge_find_entity: its ID, name, labels and reading note.
func (index *releaseIndex) methodLine(entity indexedEntity) string {
	return "编号：" + entity.EntityID + "；名称：" + entity.Name + "；标签：" + strings.Join(entity.Labels, "、") +
		"；" + index.methodNote(entity)
}

// namedIn reports whether a normalized question holds a name of at least two runes.
func namedIn(question, name string) bool {
	name = normalize(name)
	return utf8.RuneCountInString(name) >= 2 && strings.Contains(question, name)
}
