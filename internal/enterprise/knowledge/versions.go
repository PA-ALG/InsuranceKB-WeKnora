package knowledge

import (
	"strings"
	"time"
)

// Lifecycle is a product version's published sale period (PV-4a). Dates are YYYY-MM-DD and
// source_status is a snapshot taken at basis_date; an empty string is an unknown value.
type Lifecycle struct {
	SaleStart    string `json:"sale_start"`
	SaleEnd      string `json:"sale_end"`
	SourceStatus string `json:"source_status"`
	BasisCommit  string `json:"basis_commit"`
	BasisDate    string `json:"basis_date"`
}

// Family is the brand family a version is grouped under; it never identifies a product.
type Family struct {
	Key         string `json:"key"`
	DisplayName string `json:"display_name"`
}

// SaleStatus is computed when a release is read and never stored (PV-4b Spec §1).
type SaleStatus string

// The four sale statuses.
const (
	SaleOnSale       SaleStatus = "on_sale"
	SaleDiscontinued SaleStatus = "discontinued"
	SaleNotYet       SaleStatus = "not_yet_on_sale"
	SaleUnknown      SaleStatus = "unknown"
)

// businessZone is Asia/Shanghai as a fixed offset: China has kept no daylight saving time since
// 1991, and a fixed offset keeps the platform and the browser on the same day without a time
// zone database. A per-Space zone replaces it when Spaces carry one (PV-4 §4).
var businessZone = time.FixedZone("UTC+8", 8*60*60)

// BusinessDay is the calendar day of an instant in the business time zone.
func BusinessDay(instant time.Time) string { return instant.In(businessZone).Format(dateLayout) }

const dateLayout = "2006-01-02"

// SaleStatusOn applies the first rule that holds (Spec §1.2): dates known to have passed win
// over the source snapshot, and an unknown end alone never means a version is on sale.
func SaleStatusOn(lifecycle *Lifecycle, day string) SaleStatus {
	switch {
	case lifecycle == nil:
		return SaleUnknown
	case lifecycle.SaleStart != "" && day < lifecycle.SaleStart:
		return SaleNotYet
	case lifecycle.SaleEnd != "" && day >= lifecycle.SaleEnd:
		return SaleDiscontinued
	case lifecycle.SaleStart == "":
		return SaleUnknown
	case lifecycle.SaleEnd != "" && lifecycle.SourceStatus != string(SaleDiscontinued):
		return SaleOnSale
	case lifecycle.SaleEnd == "" && lifecycle.SourceStatus == string(SaleOnSale):
		return SaleOnSale
	}
	return SaleUnknown
}

// WithClock returns a service that evaluates sale status at the given clock's business day.
func (s *Service) WithClock(now func() time.Time) *Service {
	return &Service{reader: s.reader, now: now}
}

func (s *Service) today() string {
	if s.now == nil {
		return BusinessDay(time.Now())
	}
	return BusinessDay(s.now())
}

var saleWords = map[SaleStatus]string{
	SaleOnSale: "在售", SaleDiscontinued: "停售", SaleNotYet: "未开售", SaleUnknown: "销售状态未知",
}

// saleText is the status wording and, for an open-ended sale, the date its snapshot was taken.
func saleText(entity Entity) (word, basis string) {
	word = saleWords[entity.Status]
	if entity.Status == SaleOnSale && entity.Lifecycle.SaleEnd == "" && entity.Lifecycle.BasisDate != "" {
		basis = "据 " + entity.Lifecycle.BasisDate + " 数据"
	}
	return word, basis
}

func periodText(lifecycle *Lifecycle) string {
	switch {
	case lifecycle == nil || lifecycle.SaleStart == "" && lifecycle.SaleEnd == "":
		return ""
	case lifecycle.SaleEnd == "":
		return lifecycle.SaleStart + " 起"
	case lifecycle.SaleStart == "":
		return "至 " + lifecycle.SaleEnd
	}
	return lifecycle.SaleStart + " 至 " + lifecycle.SaleEnd
}

// versionLabel follows an entity's name wherever its fields are quoted. Entities without a
// lifecycle get none, so their text stays exactly as before version data was published.
func versionLabel(entity Entity) string {
	if entity.Lifecycle == nil {
		return ""
	}
	word, basis := saleText(entity)
	if basis != "" {
		word += "，" + basis
	}
	if period := periodText(entity.Lifecycle); period != "" {
		word += "；销售期 " + period
	}
	return "（" + word + "）"
}

// FieldTitle is a field's citation title: entity name, version label and field title.
func FieldTitle(field Field) string {
	return field.EntityName + field.EntityVersion + " · " + field.FieldTitle
}

// entityLine describes an entity for knowledge_find_entity; version parts appear only when known.
func (index *releaseIndex) entityLine(entity Entity) string {
	line := "产品编号：" + entity.EntityID + "；名称：" + entity.Name
	if entity.Lifecycle != nil {
		word, basis := saleText(entity)
		if entity.Status == SaleUnknown {
			word = "未知"
		}
		if basis != "" {
			word += "（" + basis + "）"
		}
		line += "；销售状态：" + word
		if period := periodText(entity.Lifecycle); period != "" {
			line += "；销售期：" + period
		}
	}
	if entity.Family != nil {
		line += "；系列：" + entity.Family.DisplayName
	}
	for _, link := range []struct {
		title string
		ids   []string
	}{{"前一版本", entity.Predecessors}, {"后续版本", entity.Successors}} {
		if len(link.ids) == 0 {
			continue
		}
		named := make([]string, 0, len(link.ids))
		for _, id := range link.ids {
			named = append(named, id+"（"+index.entities[index.entityByID[id]].Name+"）")
		}
		line += "；" + link.title + "：" + strings.Join(named, "、")
	}
	return line
}

type relationPayload struct {
	Predicate string `json:"predicate"`
	From      string `json:"from"`
	To        string `json:"to"`
}

// linkVersions records supersedes relations whose two ends are visible entities of the release
// (from is the newer version); PV-4a validated their identity when they were published.
func (index *releaseIndex) linkVersions(relations []relationPayload) {
	for _, relation := range relations {
		from, okFrom := index.entityByID[relation.From]
		to, okTo := index.entityByID[relation.To]
		if relation.Predicate != "supersedes" || !okFrom || !okTo || from == to ||
			index.entities[from].placeholder || index.entities[to].placeholder {
			continue
		}
		newer, older := &index.entities[from].Entity, &index.entities[to].Entity
		if !contains(newer.Predecessors, older.EntityID) {
			newer.Predecessors = append(newer.Predecessors, older.EntityID)
			older.Successors = append(older.Successors, newer.EntityID)
		}
	}
}

// evaluate sets every entity's sale status for the read's business day.
func (index *releaseIndex) evaluate(day string) {
	for i := range index.entities {
		index.entities[i].Status = SaleStatusOn(index.entities[i].Lifecycle, day)
	}
}

func contains(values []string, value string) bool {
	for _, item := range values {
		if item == value {
			return true
		}
	}
	return false
}
