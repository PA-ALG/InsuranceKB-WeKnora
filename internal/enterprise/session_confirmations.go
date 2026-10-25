package enterprise

import (
	"github.com/gin-gonic/gin"
)

// MountSessionConfirmations exposes only browser answers. The caller supplies the role guard
// (an answer changes what is compiled and published, so the router requires an admin).
func MountSessionConfirmations(r gin.IRouter, deps SessionDeps, guards ...gin.HandlerFunc) {
	view := sessionConfirmationRoutes(r.Group("", checkSessionRead), deps, guards...)
	view.POST("/confirmations/:confirmation_id/answers", func(c *gin.Context) {
		answerConfirmation(c, deps.Confirmations)
	})
}

func sessionConfirmationRoutes(group *gin.RouterGroup, deps SessionDeps, guards ...gin.HandlerFunc) *gin.RouterGroup {
	configured := group.Group("", func(c *gin.Context) {
		if _, ok := confirmationPrincipal(c, deps.Confirmations, true); ok {
			c.Next()
		}
	})
	return sessionSpaceRoutes(configured, deps.Spaces, guards...)
}
