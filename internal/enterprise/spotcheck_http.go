package enterprise

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"unicode/utf8"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
)

const maxSamplesBody = 256 << 10

func spotCheckPrincipal(c *gin.Context, service *spotcheck.Service, session bool) (release.Principal, bool) {
	if service == nil {
		c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{
			"success": false, "code": "SERVICE_UNAVAILABLE", "error": "spot checks are unavailable",
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

func submitSamples(c *gin.Context, service *spotcheck.Service) {
	p, ok := spotCheckPrincipal(c, service, false)
	if !ok {
		return
	}
	var in struct {
		Samples []struct {
			Slug    string `json:"slug"`
			Stratum string `json:"stratum"`
		} `json:"samples"`
	}
	err := decodeSpotCheckBody(c, &in, maxSamplesBody, spotcheck.ErrorSampleInvalid, "samples", "slug", "stratum")
	if err != nil {
		writeError(c, err)
		return
	}
	items := make([]spotcheck.SampleInput, len(in.Samples))
	for i, sample := range in.Samples {
		items[i] = spotcheck.SampleInput{Slug: sample.Slug, Stratum: sample.Stratum}
	}
	samples, err := service.Submit(c.Request.Context(), p, c.Param("space_id"), c.Param("release_id"), items)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": gin.H{"samples": samples}})
}

func listSamples(c *gin.Context, service *spotcheck.Service, session bool) {
	p, ok := spotCheckPrincipal(c, service, session)
	if !ok {
		return
	}
	samples, err := service.List(c.Request.Context(), p, c.Param("space_id"), spotcheck.Filter{
		Status: c.Query("status"), ReleaseID: c.Query("release"),
	})
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"samples": samples}})
}

func decideSample(c *gin.Context, service *spotcheck.Service) {
	p, ok := spotCheckPrincipal(c, service, true)
	if !ok {
		return
	}
	var in struct {
		Outcome string `json:"outcome"`
		Note    string `json:"note"`
	}
	err := decodeSpotCheckBody(c, &in, maxControlBody, spotcheck.ErrorVerdictInvalid, "outcome", "note")
	if err != nil {
		writeError(c, err)
		return
	}
	verdict, err := service.Decide(
		c.Request.Context(), p, c.Param("space_id"), c.Param("sample_id"), in.Outcome, in.Note,
	)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": gin.H{"verdict": verdict}})
}

// Scan decoded keys before binding: encoding/json otherwise accepts duplicates and case aliases.
// The route's finite key set also rejects aliases such as Outcome/outcome before struct binding.
func decodeSpotCheckBody(c *gin.Context, into any, limit int64, code string, keys ...string) error {
	invalid := &release.Error{Code: code, Detail: "request body is not a valid JSON object"}
	raw, err := io.ReadAll(io.LimitReader(c.Request.Body, limit+1))
	if err != nil || int64(len(raw)) > limit || !utf8.Valid(raw) {
		return invalid
	}
	allowed := make(map[string]bool, len(keys))
	for _, key := range keys {
		allowed[key] = true
	}
	scan := json.NewDecoder(bytes.NewReader(raw))
	scan.UseNumber()
	object, err := scanSpotCheckJSON(scan, allowed, 0)
	if err != nil || !object {
		return invalid
	}
	if _, err := scan.Token(); !errors.Is(err, io.EOF) {
		return invalid
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(into) != nil {
		return invalid
	}
	return nil
}

func scanSpotCheckJSON(decoder *json.Decoder, allowed map[string]bool, depth int) (bool, error) {
	if depth > 64 {
		return false, errors.New("JSON nesting exceeds limit")
	}
	token, err := decoder.Token()
	if err != nil {
		return false, err
	}
	switch token {
	case json.Delim('{'):
		seen := map[string]bool{}
		for decoder.More() {
			key, err := decoder.Token()
			if err != nil {
				return false, err
			}
			name, ok := key.(string)
			if !ok || !allowed[name] || seen[name] {
				return false, errors.New("unknown or repeated JSON key")
			}
			seen[name] = true
			if _, err := scanSpotCheckJSON(decoder, allowed, depth+1); err != nil {
				return false, err
			}
		}
		end, err := decoder.Token()
		if err != nil || end != json.Delim('}') {
			return false, errors.New("unterminated JSON object")
		}
		return true, nil
	case json.Delim('['):
		for decoder.More() {
			if _, err := scanSpotCheckJSON(decoder, allowed, depth+1); err != nil {
				return false, err
			}
		}
		end, err := decoder.Token()
		if err != nil || end != json.Delim(']') {
			return false, errors.New("unterminated JSON array")
		}
	}
	return false, nil
}
