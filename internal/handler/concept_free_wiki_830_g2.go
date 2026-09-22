package handler

import (
	"context"
	"net/http"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
)

type conceptFreeWikiHTTPService830G2 interface {
	ReadConceptPage830G2(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
	) (*service.ConceptPageRead830G2, error)
}

type conceptCitationAuthorityIssuer830G2 interface {
	IssueConceptCitationAuthority830G2(context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope, string, string, string) (*service.ConceptCitationContentAuthority830G2, error)
}

type conceptPageQueryReader830G3 interface {
	ReadConceptPageQuery830G3(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		[]string,
		bool,
	) (*service.ConceptPageRead830G2, error)
}

type conceptCitationQueryIssuer830G3 interface {
	IssueConceptCitationQuery830G3(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
		[]string,
		bool,
	) (*service.ConceptCitationContentAuthority830G2, error)
}

type ConceptFreeWikiHandler830G2 struct {
	service conceptFreeWikiHTTPService830G2
}

func NewConceptFreeWikiHandler830G2(source any) *ConceptFreeWikiHandler830G2 {
	var reader conceptFreeWikiHTTPService830G2
	switch value := source.(type) {
	case conceptFreeWikiHTTPService830G2:
		reader = value
	case *SchemaWikiHandler:
		if value != nil {
			reader, _ = value.schemaService.(conceptFreeWikiHTTPService830G2)
		}
	}
	return &ConceptFreeWikiHandler830G2{service: reader}
}

func (h *ConceptFreeWikiHandler830G2) ReadPage(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	memberID := strings.TrimSpace(c.Param("member_id"))
	if err != nil || memberID == "" {
		if err == nil {
			err = service.ErrWikiReleaseNotFound
		}
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.service == nil {
		writeSchemaWikiError(c, service.ErrNoSchemaWikiActiveRelease)
		return
	}
	values := c.Request.URL.Query()
	releaseOccurrences := values["release_id"]
	_, preparationPresent := values["preparation_id"]
	var read *service.ConceptPageRead830G2
	if queryReader, ok := h.service.(conceptPageQueryReader830G3); ok {
		read, err = queryReader.ReadConceptPageQuery830G3(
			c.Request.Context(), principal, scope, memberID,
			releaseOccurrences, preparationPresent,
		)
	} else {
		selectedRelease := ""
		if len(releaseOccurrences) > 0 {
			selectedRelease = strings.TrimSpace(releaseOccurrences[0])
		}
		read, err = h.service.ReadConceptPage830G2(
			c.Request.Context(), principal, scope, memberID, selectedRelease,
		)
	}
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": read})
}

func (h *ConceptFreeWikiHandler830G2) PreviewCitation(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	memberID := strings.TrimSpace(c.Param("member_id"))
	citationID := strings.TrimSpace(c.Param("citation_id"))
	values := c.Request.URL.Query()
	releaseOccurrences := values["release_id"]
	_, preparationPresent := values["preparation_id"]
	releaseID := ""
	if len(releaseOccurrences) > 0 {
		releaseID = strings.TrimSpace(releaseOccurrences[0])
	}
	if err != nil || memberID == "" || citationID == "" || releaseID == "" {
		if err == nil {
			err = service.ErrSchemaWikiCitationUnavailable
		}
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.service == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiCitationUnavailable)
		return
	}
	var authority *service.ConceptCitationContentAuthority830G2
	if queryIssuer, ok := h.service.(conceptCitationQueryIssuer830G3); ok {
		authority, err = queryIssuer.IssueConceptCitationQuery830G3(
			c.Request.Context(), principal, scope, memberID, citationID,
			releaseOccurrences, preparationPresent,
		)
	} else {
		issuer, ok := h.service.(conceptCitationAuthorityIssuer830G2)
		if !ok {
			writeSchemaWikiError(c, service.ErrConceptSourceAuthorityUnavailable830G2)
			return
		}
		authority, err = issuer.IssueConceptCitationAuthority830G2(
			c.Request.Context(), principal, scope, releaseID, memberID, citationID,
		)
	}
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": authority})
}
