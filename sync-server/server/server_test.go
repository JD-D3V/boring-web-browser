package server

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"google.golang.org/protobuf/proto"

	pb "github.com/JD-D3V/boring-web-browser/sync-server/protocol"
	"github.com/JD-D3V/boring-web-browser/sync-server/store"
)

// The bookmark field number in EntitySpecifics, which doubles as the
// data type id for bookmarks.
const bookmarkType = 32904

func newTestServer(t *testing.T) http.Handler {
	t.Helper()
	st, err := store.New("")
	if err != nil {
		t.Fatalf("store: %v", err)
	}
	return New(st).Handler()
}

func post(t *testing.T, h http.Handler, msg *pb.ClientToServerMessage,
) *pb.ClientToServerResponse {
	t.Helper()
	body, err := proto.Marshal(msg)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/command/",
		bytes.NewReader(body))
	req.Header.Set("Authorization", tokenHeader(testToken))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d", rec.Code)
	}
	raw, _ := io.ReadAll(rec.Body)
	resp := &pb.ClientToServerResponse{}
	if err := proto.Unmarshal(raw, resp); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	return resp
}

func bookmark(title string) *pb.SyncEntity {
	return &pb.SyncEntity{
		IdString: proto.String("item-" + title),
		Name:     proto.String(title),
		Specifics: &pb.EntitySpecifics{
			SpecificsVariant: &pb.EntitySpecifics_Bookmark{
				Bookmark: &pb.BookmarkSpecifics{
					// In the real browser this is already encrypted.
					Guid: proto.String("guid-" + title),
				},
			},
		},
	}
}

func TestCommitThenGetUpdates(t *testing.T) {
	h := newTestServer(t)

	commit := post(t, h, &pb.ClientToServerMessage{
		Share:           proto.String(""),
		MessageContents: pb.ClientToServerMessage_COMMIT.Enum(),
		Commit: &pb.CommitMessage{
			Entries: []*pb.SyncEntity{bookmark("one"), bookmark("two")},
		},
	})
	if got := len(commit.GetCommit().GetEntryresponse()); got != 2 {
		t.Fatalf("want 2 entry responses, got %d", got)
	}
	for _, entry := range commit.GetCommit().GetEntryresponse() {
		if entry.GetResponseType() != pb.CommitResponse_SUCCESS {
			t.Fatalf("commit was not a success: %v", entry.GetResponseType())
		}
		if entry.GetVersion() == 0 {
			t.Fatal("server did not give the item a version")
		}
	}
	birthday := commit.GetStoreBirthday()
	if birthday == "" {
		t.Fatal("no store birthday")
	}

	// A fresh device asks for everything.
	updates := post(t, h, &pb.ClientToServerMessage{
		Share:           proto.String(""),
		MessageContents: pb.ClientToServerMessage_GET_UPDATES.Enum(),
		StoreBirthday:   proto.String(birthday),
		GetUpdates: &pb.GetUpdatesMessage{
			FromProgressMarker: []*pb.DataTypeProgressMarker{
				{DataTypeId: proto.Int32(bookmarkType)},
			},
		},
	})
	entries := updates.GetGetUpdates().GetEntries()
	if len(entries) != 2 {
		t.Fatalf("want 2 items back, got %d", len(entries))
	}
	if entries[0].GetName() != "one" {
		t.Fatalf("wrong order or name: %q", entries[0].GetName())
	}
	if entries[0].GetSpecifics().GetBookmark().GetGuid() != "guid-one" {
		t.Fatal("the stored payload did not come back unchanged")
	}

	// Asking again from where it stopped gives nothing new.
	token := updates.GetGetUpdates().GetNewProgressMarker()[0].GetToken()
	again := post(t, h, &pb.ClientToServerMessage{
		Share:           proto.String(""),
		MessageContents: pb.ClientToServerMessage_GET_UPDATES.Enum(),
		StoreBirthday:   proto.String(birthday),
		GetUpdates: &pb.GetUpdatesMessage{
			FromProgressMarker: []*pb.DataTypeProgressMarker{
				{DataTypeId: proto.Int32(bookmarkType), Token: token},
			},
		},
	})
	if got := len(again.GetGetUpdates().GetEntries()); got != 0 {
		t.Fatalf("want nothing new, got %d items", got)
	}

	// A new change shows up for that same device.
	post(t, h, &pb.ClientToServerMessage{
		Share:           proto.String(""),
		MessageContents: pb.ClientToServerMessage_COMMIT.Enum(),
		StoreBirthday:   proto.String(birthday),
		Commit: &pb.CommitMessage{
			Entries: []*pb.SyncEntity{bookmark("three")},
		},
	})
	third := post(t, h, &pb.ClientToServerMessage{
		Share:           proto.String(""),
		MessageContents: pb.ClientToServerMessage_GET_UPDATES.Enum(),
		StoreBirthday:   proto.String(birthday),
		GetUpdates: &pb.GetUpdatesMessage{
			FromProgressMarker: []*pb.DataTypeProgressMarker{
				{DataTypeId: proto.Int32(bookmarkType), Token: token},
			},
		},
	})
	if got := len(third.GetGetUpdates().GetEntries()); got != 1 {
		t.Fatalf("want 1 new item, got %d", got)
	}
}

func TestWrongBirthdayIsRejected(t *testing.T) {
	h := newTestServer(t)
	first := post(t, h, &pb.ClientToServerMessage{
		Share:           proto.String(""),
		MessageContents: pb.ClientToServerMessage_GET_UPDATES.Enum(),
		GetUpdates:      &pb.GetUpdatesMessage{},
	})
	if first.GetErrorCode() != pb.SyncEnums_SUCCESS {
		t.Fatalf("first call failed: %v", first.GetErrorCode())
	}
	stale := post(t, h, &pb.ClientToServerMessage{
		Share:           proto.String(""),
		MessageContents: pb.ClientToServerMessage_GET_UPDATES.Enum(),
		StoreBirthday:   proto.String("an-old-birthday"),
		GetUpdates:      &pb.GetUpdatesMessage{},
	})
	if stale.GetErrorCode() != pb.SyncEnums_NOT_MY_BIRTHDAY {
		t.Fatalf("want NOT_MY_BIRTHDAY, got %v", stale.GetErrorCode())
	}
}

func TestChainsAreSeparate(t *testing.T) {
	st, err := store.New("")
	if err != nil {
		t.Fatal(err)
	}
	h := New(st).Handler()

	body, _ := proto.Marshal(&pb.ClientToServerMessage{
		Share:           proto.String(""),
		MessageContents: pb.ClientToServerMessage_COMMIT.Enum(),
		Commit: &pb.CommitMessage{
			Entries: []*pb.SyncEntity{bookmark("private")},
		},
	})
	req := httptest.NewRequest(http.MethodPost, "/v1/command/",
		bytes.NewReader(body))
	req.Header.Set("Authorization", tokenHeader("chain-a-0123456789abcdef"))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	// A different chain must not see it.
	body2, _ := proto.Marshal(&pb.ClientToServerMessage{
		Share:           proto.String(""),
		MessageContents: pb.ClientToServerMessage_GET_UPDATES.Enum(),
		GetUpdates: &pb.GetUpdatesMessage{
			FromProgressMarker: []*pb.DataTypeProgressMarker{
				{DataTypeId: proto.Int32(bookmarkType)},
			},
		},
	})
	req2 := httptest.NewRequest(http.MethodPost, "/v1/command/",
		bytes.NewReader(body2))
	req2.Header.Set("Authorization", tokenHeader("chain-b-0123456789abcdef"))
	rec2 := httptest.NewRecorder()
	h.ServeHTTP(rec2, req2)
	raw, _ := io.ReadAll(rec2.Body)
	resp := &pb.ClientToServerResponse{}
	if err := proto.Unmarshal(raw, resp); err != nil {
		t.Fatal(err)
	}
	if got := len(resp.GetGetUpdates().GetEntries()); got != 0 {
		t.Fatalf("one chain could see another chain's items: %d", got)
	}
}

// ---- Authentication ----

// A token long enough to be accepted. Real ones come from the browser.
const testToken = "test-chain-0123456789abcdef"

func tokenHeader(token string) string { return "Bearer " + token }

// commitAs sends one commit using the given Authorization header value
// (empty means send no header at all) and returns the status code.
func commitAs(t *testing.T, h http.Handler, auth string) int {
	t.Helper()
	body, _ := proto.Marshal(&pb.ClientToServerMessage{
		Share:           proto.String(""),
		MessageContents: pb.ClientToServerMessage_COMMIT.Enum(),
		Commit: &pb.CommitMessage{
			Entries: []*pb.SyncEntity{bookmark("x")},
		},
	})
	req := httptest.NewRequest(http.MethodPost, "/v1/command/",
		bytes.NewReader(body))
	if auth != "" {
		req.Header.Set("Authorization", auth)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec.Code
}

func TestRequestWithoutTokenIsRejected(t *testing.T) {
	h := newTestServer(t)
	if got := commitAs(t, h, ""); got != http.StatusUnauthorized {
		t.Fatalf("no token should be refused, got status %d", got)
	}
}

func TestShortTokenIsRejected(t *testing.T) {
	h := newTestServer(t)
	if got := commitAs(t, h, tokenHeader("tooshort")); got != http.StatusUnauthorized {
		t.Fatalf("short token should be refused, got status %d", got)
	}
}

// The token must not be accepted from the query string: it would end up
// in server logs and proxy logs.
func TestQueryParameterTokenIsRejected(t *testing.T) {
	h := newTestServer(t)
	body, _ := proto.Marshal(&pb.ClientToServerMessage{
		Share:           proto.String(""),
		MessageContents: pb.ClientToServerMessage_COMMIT.Enum(),
	})
	req := httptest.NewRequest(http.MethodPost,
		"/v1/command/?client_id="+testToken, bytes.NewReader(body))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("query string token should be refused, got %d", rec.Code)
	}
}

// Two different tokens must never share a chain. These two are the case
// the old scheme got wrong: it stripped punctuation, so both became
// "alicetoken0123456789" and the second person read the first's data.
func TestSimilarTokensDoNotShareAChain(t *testing.T) {
	a := "alicetoken0123456789"
	b := "alice.token.0123456789"

	idA, err := chainID(withToken(a))
	if err != nil {
		t.Fatalf("token a refused: %v", err)
	}
	idB, err := chainID(withToken(b))
	if err != nil {
		t.Fatalf("token b refused: %v", err)
	}
	if idA == idB {
		t.Fatalf("two different tokens landed on the same chain: %s", idA)
	}
}

// The chain id must not contain the token itself, since it is used as a
// file name on disk.
func TestChainIDDoesNotLeakTheToken(t *testing.T) {
	id, err := chainID(withToken(testToken))
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(id, "test-chain") {
		t.Fatalf("chain id contains the raw token: %s", id)
	}
	if len(id) != 64 {
		t.Fatalf("want a 64 character digest, got %d", len(id))
	}
}

func withToken(token string) *http.Request {
	req := httptest.NewRequest(http.MethodPost, "/v1/command/", nil)
	req.Header.Set("Authorization", tokenHeader(token))
	return req
}
