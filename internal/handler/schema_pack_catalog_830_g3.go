package handler

import (
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"sync"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/gin-gonic/gin"
)

const (
	schemaPackCatalog830G3ID          = "schema_catalog_insurance_product"
	schemaPackCatalog830G3Version     = "2026-08-12-v5"
	schemaPackCatalog830G3Contract    = "schema-pack-catalog.830.g3.v1"
	schemaPackCatalog830G3WireSHA256  = "0d5ed6a5789362f1c72ebad5bbc47a64e1d71bc122890da96d976ec01256a3f9"
	schemaPackCatalog830G3ContentHash = "b4b8cd9c797442c3581c8721834abb3f6ec716057509dad4ac254f79fc0a97bd"
)

//go:embed schema_pack_catalog_830_g3.generated.json
var schemaPackCatalog830G3Bytes []byte

var (
	schemaPackCatalog830G3Once sync.Once
	schemaPackCatalog830G3Raw  json.RawMessage
	schemaPackCatalog830G3Err  error
)

func loadSchemaPackCatalog830G3() (json.RawMessage, error) {
	schemaPackCatalog830G3Once.Do(func() {
		sum := sha256.Sum256(schemaPackCatalog830G3Bytes)
		if hex.EncodeToString(sum[:]) != schemaPackCatalog830G3WireSHA256 {
			schemaPackCatalog830G3Err = errors.New("schema pack catalog asset hash mismatch")
			return
		}
		var identity struct {
			Contract       string `json:"contract"`
			CatalogID      string `json:"catalog_id"`
			CatalogVersion string `json:"catalog_version"`
			CatalogSHA256  string `json:"catalog_sha256"`
		}
		if json.Unmarshal(schemaPackCatalog830G3Bytes, &identity) != nil ||
			identity.Contract != schemaPackCatalog830G3Contract ||
			identity.CatalogID != schemaPackCatalog830G3ID ||
			identity.CatalogVersion != schemaPackCatalog830G3Version ||
			identity.CatalogSHA256 != schemaPackCatalog830G3ContentHash {
			schemaPackCatalog830G3Err = errors.New("schema pack catalog asset identity mismatch")
			return
		}
		schemaPackCatalog830G3Raw = append(json.RawMessage(nil), schemaPackCatalog830G3Bytes...)
	})
	return schemaPackCatalog830G3Raw, schemaPackCatalog830G3Err
}

// ReadSchemaPackCatalog830G3 returns the frozen catalog only after the current
// scope and both KB ACLs have been sealed by the existing read route.
func (h *SchemaWikiHandler) ReadSchemaPackCatalog830G3(c *gin.Context) {
	c.Header("Cache-Control", "private, no-store")
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err == nil {
		err = service.NewContextWikiReleaseAccessVerifier().VerifyWikiReleaseAccess(
			c.Request.Context(),
			service.WikiReleaseAccessRequest{
				Principal: principal,
				Scope:     scope,
				Operation: "schema_pack_catalog_830_g3.read",
			},
		)
	}
	if err != nil {
		writeWikiReleaseError(c, service.ErrWikiReleaseAccessDenied)
		return
	}
	if c.Param("catalog_id") != schemaPackCatalog830G3ID ||
		c.Param("catalog_version") != schemaPackCatalog830G3Version {
		writeWikiReleaseError(c, service.ErrWikiReleaseNotFound)
		return
	}
	catalog, err := loadSchemaPackCatalog830G3()
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": catalog})
}
