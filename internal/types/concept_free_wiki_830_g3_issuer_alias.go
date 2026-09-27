package types

// Issuer declarations belong to the trusted, hashed policy. Source proposals
// remain immutable; only comparisons and derived joint anchors use this value.
func (policy BatchResolutionPolicy830G3) canonicalIssuer(value, spaceID string) string {
	for _, declaration := range policy.IssuerAliases {
		scoped := false
		for _, space := range declaration.SpaceIDs {
			if space == spaceID {
				scoped = true
			}
		}
		if !scoped {
			continue
		}
		for _, name := range append([]string{declaration.CanonicalName}, declaration.Aliases...) {
			if normalizedIdentity830G3(value) == normalizedIdentity830G3(name) {
				return declaration.CanonicalName
			}
		}
	}
	return value
}

func validIssuerAliases830G3(declarations []IssuerAliasDeclaration830G3) bool {
	previous := ""
	occupied := map[string]bool{}
	for _, declaration := range declarations {
		if !validStructuredText830G3(declaration.CanonicalName) || !validStructuredText830G3(declaration.ConfirmationRef) || declaration.CanonicalName <= previous || len(declaration.Aliases) == 0 || len(declaration.SpaceIDs) == 0 || !sortedUniquePlain830G3(declaration.Aliases) || !sortedUniquePlain830G3(declaration.SpaceIDs) {
			return false
		}
		previous = declaration.CanonicalName
		names := append([]string{declaration.CanonicalName}, declaration.Aliases...)
		normalized := map[string]bool{}
		for _, name := range names {
			if !validStructuredText830G3(name) || normalized[normalizedIdentity830G3(name)] {
				return false
			}
			normalized[normalizedIdentity830G3(name)] = true
		}
		for _, space := range declaration.SpaceIDs {
			if !validStructuredText830G3(space) {
				return false
			}
			for name := range normalized {
				key := space + "\x00" + name
				if occupied[key] {
					return false
				}
				occupied[key] = true
			}
		}
	}
	return true
}
