package config

// ProductIngestionConfig connects browser uploads to one deployed Harness scope.
// Explicit capacities apply to uploads generally; no product-specific file count is encoded.
type ProductIngestionConfig struct {
	Enabled          bool   `yaml:"enabled"`
	BaseURL          string `yaml:"base_url"`
	Credential       string `yaml:"credential" json:"-"`
	TenantID         uint64 `yaml:"tenant_id"`
	SpaceID          string `yaml:"space_id"`
	RawKBID          string `yaml:"raw_kb_id"`
	WikiKBID         string `yaml:"wiki_kb_id"`
	TimeoutSeconds   int    `yaml:"timeout_seconds"`
	MaxResponseBytes int64  `yaml:"max_response_bytes"`
	MaxUploadFiles   int    `yaml:"max_upload_files"`
	MaxUploadBytes   int64  `yaml:"max_upload_bytes"`
}
