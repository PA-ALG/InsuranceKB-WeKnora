package handler

import (
	"context"
	"net/http"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
)

type batchProductBindingsReader830G3 interface {
	ReadBatchProductBindings830G3(context.Context, types.WikiReleasePrincipal,
		types.WikiReleaseScope, string) (*service.BatchProductBindingsRead830G3, error)
}

func (h *SchemaWikiHandler) ReadCurrentProductBindings830G3(c *gin.Context) {
	h.readProductBindings830G3(c, "")
}

func (h *SchemaWikiHandler) ReadPreparationProductBindings830G3(c *gin.Context) {
	if c.Param("preparation_id") == "" {
		writeSchemaWikiError(c, service.ErrSchemaWikiPreparationInvalid)
		return
	}
	h.readProductBindings830G3(c, c.Param("preparation_id"))
}

func (h *SchemaWikiHandler) readProductBindings830G3(c *gin.Context, preparationID string) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiPreparationInvalid)
		return
	}
	reader, ok := h.schemaService.(batchProductBindingsReader830G3)
	if !ok {
		writeSchemaWikiError(c, service.ErrSchemaWikiPreparationInvalid)
		return
	}
	result, err := reader.ReadBatchProductBindings830G3(c.Request.Context(), principal, scope, preparationID)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": result})
}
