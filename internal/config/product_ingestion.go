package config

import (
	"fmt"
	"strings"
)

const NativeCandidatesPolicy = "native-candidates.830.v1"

// ProductIngestionConfig is the scope of the retired G3 product ingestion. Its upload bridge
// was removed in S7d-2a; only the native-write policy below still reads it, until S7d-2b.
type ProductIngestionConfig struct {
	WikiProducerPolicy string `yaml:"wiki_producer_policy"`
	Enabled            bool   `yaml:"enabled"`
	TenantID           uint64 `yaml:"tenant_id"`
	SpaceID            string `yaml:"space_id"`
	RawKBID            string `yaml:"raw_kb_id"`
	WikiKBID           string `yaml:"wiki_kb_id"`
}

// NativeWikiWritesDisabled is the single native-write policy gate for the
// configured product RAW and serving Wiki. Unrelated KBs keep native behavior.
func (c *Config) NativeWikiWritesDisabled(tenantID uint64, kbID string) bool {
	if c == nil || c.ProductIngestion == nil {
		return false
	}
	p := c.ProductIngestion
	return p.Enabled && p.WikiProducerPolicy == NativeCandidatesPolicy &&
		p.TenantID == tenantID && (p.RawKBID == kbID || p.WikiKBID == kbID)
}

func validateProductWikiProducerPolicy(c *Config) error {
	if c == nil || c.ProductIngestion == nil || c.ProductIngestion.WikiProducerPolicy == "" {
		return nil
	}
	p := c.ProductIngestion
	if p.WikiProducerPolicy != NativeCandidatesPolicy || !p.Enabled || p.TenantID == 0 ||
		strings.TrimSpace(p.SpaceID) == "" || strings.TrimSpace(p.RawKBID) == "" ||
		strings.TrimSpace(p.WikiKBID) == "" || p.RawKBID == p.WikiKBID {
		return fmt.Errorf("product_ingestion.wiki_producer_policy requires a supported policy and complete enabled scope")
	}
	return nil
}

// NativeCandidateScopeEnabled also binds Space and both KBs at the producer API.
func (c *Config) NativeCandidateScopeEnabled(tenantID uint64, spaceID, rawKBID, wikiKBID string) bool {
	if !c.NativeWikiWritesDisabled(tenantID, rawKBID) {
		return false
	}
	p := c.ProductIngestion
	return p.SpaceID == spaceID && p.RawKBID == rawKBID && p.WikiKBID == wikiKBID
}
