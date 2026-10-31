package database

import (
	"fmt"
	"testing"

	"github.com/Tencent/WeKnora/deploy/upstream"
	"github.com/stretchr/testify/require"
)

func TestClassifyLegacyW1Origin(t *testing.T) {
	officialHead := upstream.OfficialMigrationHead()
	tests := []struct {
		name    string
		state   legacyW1BridgeState
		want    legacyW1Origin
		wantErr string
	}{
		{
			name:  "fresh",
			state: legacyW1BridgeState{fixtureChecksumValid: true},
			want:  legacyW1OriginFresh,
		},
		{
			name: "official constructor residue is fresh",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      -1,
			},
			want: legacyW1OriginFresh,
		},
		{
			name: "pre66 at known runtime checkpoint",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      65,
				spanState:            spanNameLegacy64,
			},
			want: legacyW1OriginPre66,
		},
		{
			name: "early pre66 before span table",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      54,
			},
			want: legacyW1OriginPre66,
		},
		{
			name: "version65 without span table is partial",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      65,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "version54 with span table is partial",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      54,
				spanState:            spanNameLegacy64,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "upstream66 plus",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      officialHead,
				spanState:            spanNameExpanded255,
			},
			want: legacyW1OriginUpstream66Plus,
		},
		{
			name: "enterprise constructor residue after official migration",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      -1,
			},
			want: legacyW1OriginUpstream66Plus,
		},
		{
			name: "exact legacy66",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      66,
				w1State:              legacyW1Exact,
				spanState:            spanNameLegacy64,
			},
			want: legacyW1OriginExactLegacy66,
		},
		{
			name: "known bridged checkpoint",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        66,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      1,
			},
			want: legacyW1OriginKnownBridged,
		},
		{
			name: "packaged enterprise head at official66 is unknown",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        66,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      int64(packagedEnterpriseMigrationHead),
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "enterprise version1 remains a known upgradeable state",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      1,
			},
			want: legacyW1OriginFullCurrent,
		},
		{
			name: "packaged enterprise head at a resumable official checkpoint",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead - 1,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      int64(packagedEnterpriseMigrationHead),
			},
			want: legacyW1OriginFullCurrent,
		},
		{
			name: "full current at packaged enterprise head",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      int64(packagedEnterpriseMigrationHead),
			},
			want: legacyW1OriginFullCurrent,
		},
		{
			name: "released official75 enterprise5 is an upgradeable checkpoint",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        75,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      int64(packagedEnterpriseMigrationHead),
			},
			want: legacyW1OriginFullCurrent,
		},
		{
			name: "previous enterprise head remains upgradeable at official head",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      2,
			},
			want: legacyW1OriginFullCurrent,
		},
		{
			name: "official dirty",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      66,
				officialDirty:        true,
			},
			wantErr: "dirty",
		},
		{
			name: "enterprise dirty",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      1,
				enterpriseDirty:        true,
			},
			wantErr: "dirty",
		},
		{
			name: "legacy fixture checksum mismatch",
			state: legacyW1BridgeState{
				officialLedgerExists: true,
				officialVersion:      66,
				w1State:              legacyW1Exact,
				spanState:            spanNameLegacy64,
			},
			wantErr: "fixture checksum",
		},
		{
			name: "partial W1 schema",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      66,
				w1State:              legacyW1Partial,
				spanState:            spanNameLegacy64,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "legacy66 span already expanded without enterprise ledger",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      66,
				w1State:              legacyW1Exact,
				spanState:            spanNameExpanded255,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "official span and W1 exact without enterprise ledger",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      officialHead,
				w1State:              legacyW1Exact,
				spanState:            spanNameExpanded255,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "enterprise ledger without W1",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      1,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "enterprise version above packaged head",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        officialHead,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				enterpriseLedgerExists: true,
				enterpriseVersion:      int64(packagedEnterpriseMigrationHead) + 1,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "packaged official head exceeded",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      officialHead + 1,
				spanState:            spanNameExpanded255,
			},
			wantErr: "newer than packaged head",
		},
		{
			name: "legacy W1 with empty enterprise ledger is partial",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        66,
				w1State:                legacyW1Exact,
				spanState:              spanNameLegacy64,
				enterpriseLedgerExists: true,
				enterpriseVersion:      -1,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "enterprise constructor residue before official66 is partial",
			state: legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        65,
				spanState:              spanNameLegacy64,
				enterpriseLedgerExists: true,
				enterpriseVersion:      -1,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
		{
			name: "objects without official ledger",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				w1State:              legacyW1Exact,
			},
			wantErr: "unknown legacy W1 migration origin",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := classifyLegacyW1Origin(tt.state)
			if tt.wantErr != "" {
				require.ErrorContains(t, err, tt.wantErr)
				return
			}
			require.NoError(t, err)
			require.Equal(t, tt.want, got)
		})
	}
}

func TestClassifyLegacyW1OriginAllowsPackagedUpgradeResumeCheckpoints(t *testing.T) {
	officialHead := upstream.OfficialMigrationHead()
	for version := releasedOfficial75Checkpoint; version <= officialHead; version++ {
		t.Run(fmt.Sprintf("official%d_enterprise5", version), func(t *testing.T) {
			state := legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        version,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				dependencyState:        dependencyAnchorsExact,
				enterpriseLedgerExists: true,
				enterpriseVersion:      int64(packagedEnterpriseMigrationHead),
			}

			got, err := classifyLegacyW1Origin(state)

			require.NoError(t, err)
			require.Equal(t, legacyW1OriginFullCurrent, got)
		})
	}

	for _, version := range []int64{releasedOfficial75Checkpoint - 1, officialHead + 1} {
		t.Run(fmt.Sprintf("official%d_is_outside_packaged_chain", version), func(t *testing.T) {
			state := legacyW1BridgeState{
				fixtureChecksumValid:   true,
				officialLedgerExists:   true,
				officialVersion:        version,
				w1State:                legacyW1Exact,
				spanState:              spanNameExpanded255,
				dependencyState:        dependencyAnchorsExact,
				enterpriseLedgerExists: true,
				enterpriseVersion:      int64(packagedEnterpriseMigrationHead),
			}

			_, err := classifyLegacyW1Origin(state)

			require.Error(t, err)
		})
	}

	dirty := legacyW1BridgeState{
		fixtureChecksumValid:   true,
		officialLedgerExists:   true,
		officialVersion:        releasedOfficial75Checkpoint + 1,
		officialDirty:          true,
		w1State:                legacyW1Exact,
		spanState:              spanNameExpanded255,
		dependencyState:        dependencyAnchorsExact,
		enterpriseLedgerExists: true,
		enterpriseVersion:      int64(packagedEnterpriseMigrationHead),
	}
	_, err := classifyLegacyW1Origin(dirty)
	require.ErrorContains(t, err, "dirty")
}

func TestClassifyLegacyW1OriginRequiresDependencyAnchorsAtKnownCheckpoints(t *testing.T) {
	tests := []struct {
		name    string
		state   legacyW1BridgeState
		want    legacyW1Origin
		wantErr string
	}{
		{
			name: "fresh has no dependency anchors",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				dependencyState:      dependencyAnchorsAbsent,
			},
			want: legacyW1OriginFresh,
		},
		{
			name: "no ledger with half-created official schema blocks",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				dependencyState:      dependencyAnchorsPartial,
			},
			wantErr: "dependency anchors",
		},
		{
			name: "official checkpoint requires exact anchors",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      65,
				spanState:            spanNameLegacy64,
				dependencyState:      dependencyAnchorsExact,
			},
			want: legacyW1OriginPre66,
		},
		{
			name: "official checkpoint with missing anchors blocks",
			state: legacyW1BridgeState{
				fixtureChecksumValid: true,
				officialLedgerExists: true,
				officialVersion:      65,
				spanState:            spanNameLegacy64,
				dependencyState:      dependencyAnchorsAbsent,
			},
			wantErr: "dependency anchors",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := classifyLegacyW1Origin(tt.state)
			if tt.wantErr != "" {
				require.ErrorContains(t, err, tt.wantErr)
				return
			}
			require.NoError(t, err)
			require.Equal(t, tt.want, got)
		})
	}
}
