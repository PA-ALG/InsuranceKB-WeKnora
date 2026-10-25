package enterprise

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const maxConfirmationsBody = 512 << 10

func confirmationPrincipal(c *gin.Context, service *confirm.Service, session bool) (release.Principal, bool) {
	if service == nil {
		c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{
			"success": false, "code": "SERVICE_UNAVAILABLE", "error": "confirmations are unavailable",
		})
		return release.Principal{}, false
	}
	if session {
		if p, ok := sessionReadPrincipal(c); ok {
			return p, true
		}
		writeError(c, &release.Error{Code: release.ErrorReleaseAccessDenied, Detail: "a browser session is required"})
		return release.Principal{}, false
	}
	p, err := requestPrincipal(c)
	if err != nil {
		writeError(c, err)
		return release.Principal{}, false
	}
	return p, true
}

func submitConfirmations(c *gin.Context, service *confirm.Service) {
	p, ok := confirmationPrincipal(c, service, false)
	if !ok {
		return
	}
	var in struct {
		Items []struct {
			Subject  string           `json:"subject"`
			Revision string           `json:"revision"`
			Title    string           `json:"title"`
			Detail   string           `json:"detail"`
			Options  []confirm.Option `json:"options"`
		} `json:"items"`
	}
	err := decodeSpotCheckBody(c, &in, maxConfirmationsBody, confirm.ErrorConfirmationInvalid,
		"items", "subject", "revision", "title", "detail", "options", "key", "label")
	if err != nil {
		writeError(c, err)
		return
	}
	items := make([]confirm.ItemInput, len(in.Items))
	for i, item := range in.Items {
		items[i] = confirm.ItemInput{
			Subject: item.Subject, Revision: item.Revision, Title: item.Title, Detail: item.Detail,
			Options: item.Options,
		}
	}
	stored, err := service.Submit(c.Request.Context(), p, c.Param("space_id"), items)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": gin.H{"items": stored}})
}

func listConfirmations(c *gin.Context, service *confirm.Service, session bool) {
	p, ok := confirmationPrincipal(c, service, session)
	if !ok {
		return
	}
	items, err := service.List(c.Request.Context(), p, c.Param("space_id"), confirm.Filter{Status: c.Query("status")})
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"items": items}})
}

func closeConfirmation(c *gin.Context, service *confirm.Service) {
	p, ok := confirmationPrincipal(c, service, false)
	if !ok {
		return
	}
	var in struct {
		Reason   string `json:"reason"`
		AnswerID string `json:"answer_id"`
	}
	err := decodeSpotCheckBody(c, &in, maxControlBody, confirm.ErrorConfirmationInvalid, "reason", "answer_id")
	if err != nil {
		writeError(c, err)
		return
	}
	closure, err := service.Close(
		c.Request.Context(), p, c.Param("space_id"), c.Param("confirmation_id"), in.Reason, in.AnswerID,
	)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": gin.H{"closure": closure}})
}

func answerConfirmation(c *gin.Context, service *confirm.Service) {
	p, ok := confirmationPrincipal(c, service, true)
	if !ok {
		return
	}
	var in struct {
		OptionKey string `json:"option_key"`
		Note      string `json:"note"`
	}
	err := decodeSpotCheckBody(c, &in, maxControlBody, confirm.ErrorAnswerInvalid, "option_key", "note")
	if err != nil {
		writeError(c, err)
		return
	}
	answer, err := service.Answer(
		c.Request.Context(), p, c.Param("space_id"), c.Param("confirmation_id"), in.OptionKey, in.Note,
	)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": gin.H{"answer": answer}})
}
