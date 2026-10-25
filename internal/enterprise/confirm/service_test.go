package confirm_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
)

// Spec §2.2 allows the newline in every text and refuses every other control character.
func TestEveryTextMayHoldNewlinesButNoOtherControlCharacter(t *testing.T) {
	for name, set := range map[string]func(*confirm.ItemInput, string){
		"title":  func(i *confirm.ItemInput, v string) { i.Title = v },
		"detail": func(i *confirm.ItemInput, v string) { i.Detail = v },
		"label":  func(i *confirm.ItemInput, v string) { i.Options[0].Label = v },
	} {
		t.Run(name, func(t *testing.T) {
			ok := input("k-1")
			ok.Options = append([]confirm.Option(nil), ok.Options...)
			set(&ok, "first\nsecond")
			_, err := service(newStore()).Submit(context.Background(), alice(), space, []confirm.ItemInput{ok})
			require.NoError(t, err)
			for _, bad := range []string{"a\tb", "a\rb", "a\x7fb"} {
				item := input("k-2")
				item.Options = append([]confirm.Option(nil), item.Options...)
				set(&item, bad)
				_, err = service(newStore()).Submit(context.Background(), alice(), space, []confirm.ItemInput{item})
				require.Equal(t, "CONFIRMATION_INVALID", codeOf(t, err), "%q", bad)
			}
		})
	}
	s := service(newStore())
	item := submitOne(t, s, "k-3")
	_, err := s.Answer(context.Background(), alice(), space, item.ID, "ignore", "first\nsecond")
	require.NoError(t, err)
	_, err = s.Answer(context.Background(), alice(), space, item.ID, "ignore", "a\tb")
	require.Equal(t, "ANSWER_INVALID", codeOf(t, err))
}
