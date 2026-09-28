package file

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/utils"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss/credentials"
	"github.com/stretchr/testify/require"
)

func TestParseOssFilePath(t *testing.T) {
	tests := []struct {
		name        string
		input       string
		wantBucket  string
		wantKey     string
		wantErr     bool
		errContains string
	}{
		{
			name:       "valid path with nested key",
			input:      "oss://my-bucket/123/exports/abc123.csv",
			wantBucket: "my-bucket",
			wantKey:    "123/exports/abc123.csv",
		},
		{
			name:       "valid path with simple key",
			input:      "oss://test-bucket/key",
			wantBucket: "test-bucket",
			wantKey:    "key",
		},
		{
			name:       "valid path with deep nesting",
			input:      "oss://bucket/prefix/tenant/exports/uuid.png",
			wantBucket: "bucket",
			wantKey:    "prefix/tenant/exports/uuid.png",
		},
		{
			name:        "invalid scheme",
			input:       "s3://bucket/key",
			wantErr:     true,
			errContains: "invalid OSS file path",
		},
		{
			name:        "empty path",
			input:       "",
			wantErr:     true,
			errContains: "invalid OSS file path",
		},
		{
			name:        "bucket only no key",
			input:       "oss://bucket/",
			wantErr:     true,
			errContains: "invalid OSS file path",
		},
		{
			name:        "scheme only",
			input:       "oss://",
			wantErr:     true,
			errContains: "invalid OSS file path",
		},
		{
			name:        "no slash after bucket",
			input:       "oss://bucket",
			wantErr:     true,
			errContains: "invalid OSS file path",
		},
		{
			name:        "empty bucket name",
			input:       "oss:///some-key",
			wantErr:     true,
			errContains: "invalid OSS file path",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			bucket, key, err := parseOssFilePath(tt.input)
			if tt.wantErr {
				if err == nil {
					t.Errorf("parseOssFilePath(%q) expected error, got bucket=%q key=%q", tt.input, bucket, key)
				}
				if tt.errContains != "" && !strings.Contains(err.Error(), tt.errContains) {
					t.Errorf("parseOssFilePath(%q) error = %v, want containing %q", tt.input, err, tt.errContains)
				}
				return
			}
			if err != nil {
				t.Errorf("parseOssFilePath(%q) unexpected error: %v", tt.input, err)
				return
			}
			if bucket != tt.wantBucket {
				t.Errorf("parseOssFilePath(%q) bucket = %q, want %q", tt.input, bucket, tt.wantBucket)
			}
			if key != tt.wantKey {
				t.Errorf("parseOssFilePath(%q) key = %q, want %q", tt.input, key, tt.wantKey)
			}
		})
	}
}

func TestNewOSSClient(t *testing.T) {
	tests := []struct {
		name      string
		endpoint  string
		region    string
		accessKey string
		secretKey string
		wantErr   bool
	}{
		{
			name:      "valid parameters create client",
			endpoint:  "https://oss-cn-hangzhou.aliyuncs.com",
			region:    "cn-hangzhou",
			accessKey: "test-access-key",
			secretKey: "test-secret-key",
			wantErr:   false,
		},
		{
			name:      "custom endpoint",
			endpoint:  "https://example.com",
			region:    "cn-shanghai",
			accessKey: "ak",
			secretKey: "sk",
			wantErr:   false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			endpoint, err := url.Parse(tt.endpoint)
			require.NoError(t, err)
			t.Setenv("SSRF_WHITELIST", endpoint.Hostname())
			utils.ResetSSRFWhitelistForTest()
			t.Cleanup(utils.ResetSSRFWhitelistForTest)
			client, err := newOSSClient(tt.endpoint, tt.region, tt.accessKey, tt.secretKey)
			if tt.wantErr {
				if err == nil {
					t.Error("expected error but got nil")
				}
				return
			}
			if err != nil {
				t.Errorf("newOSSClient() unexpected error: %v", err)
				return
			}
			if client == nil {
				t.Error("expected non-nil client")
			}
		})
	}
}

func TestNewOSSClientRejectsUnsafeEndpoint(t *testing.T) {
	if _, err := newOSSClient("http://127.0.0.1:9000", "cn-hangzhou", "ak", "sk"); err == nil {
		t.Fatal("expected loopback OSS endpoint to be rejected")
	}
}

func TestCheckOssConnectivity_InvalidEndpoint(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Should fail with an invalid/unreachable endpoint
	err := CheckOssConnectivity(ctx,
		"https://invalid-oss-endpoint-that-does-not-exist.local",
		"cn-hangzhou",
		"invalid-access-key",
		"invalid-secret-key",
		"nonexistent-bucket",
	)

	if err == nil {
		t.Error("CheckOssConnectivity with invalid endpoint should return an error")
	}
}

func TestOssEnsureBucket_NonExistent(t *testing.T) {
	client, requests := newOSSBucketFailureClient(t)

	// The local service reports a missing bucket and denies its creation.
	const bucket = "this-bucket-definitely-does-not-exist-12345"
	err := ossEnsureBucket(client, bucket)
	if err == nil {
		t.Error("ossEnsureBucket with non-existent bucket should return an error")
	}
	assertOSSBucketCreationDenied(t, err, bucket, requests())
}

func TestOssEnsureBucket_CreateFails(t *testing.T) {
	client, requests := newOSSBucketFailureClient(t)

	// A real SDK NoSuchBucket response reaches PutBucket, which returns AccessDenied.
	const bucket = "weknora-nonexistent-bucket-create-fails-12345"
	err := ossEnsureBucket(client, bucket)
	if err == nil {
		t.Error("ossEnsureBucket with invalid credentials should return an error")
	}
	assertOSSBucketCreationDenied(t, err, bucket, requests())
}

// ossBucketRequest records only routing data, never request credentials.
type ossBucketRequest struct {
	method string
	path   string
	acl    bool
}

func newOSSBucketFailureClient(t *testing.T) (*oss.Client, func() []ossBucketRequest) {
	t.Helper()
	var mu sync.Mutex
	var requests []ossBucketRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		requests = append(requests, ossBucketRequest{r.Method, r.URL.Path, r.URL.Query().Has("acl")})
		mu.Unlock()
		w.Header().Set("Content-Type", "application/xml")
		status, code := http.StatusInternalServerError, "UnexpectedRequest"
		switch r.Method {
		case http.MethodGet:
			status, code = http.StatusNotFound, "NoSuchBucket"
		case http.MethodPut:
			status, code = http.StatusForbidden, "AccessDenied"
		}
		w.WriteHeader(status)
		if _, err := io.WriteString(
			w,
			"<Error><Code>"+code+"</Code><Message>fixture response</Message></Error>",
		); err != nil {
			t.Errorf("write OSS fixture response: %v", err)
		}
	}))
	t.Cleanup(server.Close)
	creds := credentials.NewStaticCredentialsProvider("test-invalid-key", "test-invalid-secret", "")
	cfg := oss.LoadDefaultConfig().
		WithCredentialsProvider(creds).
		WithRegion("cn-hangzhou").
		WithEndpoint(server.URL).
		WithUsePathStyle(true).
		WithHttpClient(server.Client()).
		WithRetryMaxAttempts(1)
	return oss.NewClient(cfg), func() []ossBucketRequest {
		mu.Lock()
		defer mu.Unlock()
		return append([]ossBucketRequest(nil), requests...)
	}
}

func assertOSSBucketCreationDenied(t *testing.T, err error, bucket string, requests []ossBucketRequest) {
	t.Helper()
	require.ErrorContains(t, err, "failed to create OSS bucket")
	var serviceErr *oss.ServiceError
	require.ErrorAs(t, err, &serviceErr)
	require.Equal(t, http.StatusForbidden, serviceErr.StatusCode)
	require.Equal(t, "AccessDenied", serviceErr.Code)
	require.Equal(t, []ossBucketRequest{
		{http.MethodGet, "/" + bucket + "/", true},
		{http.MethodPut, "/" + bucket + "/", false},
	}, requests)
}
