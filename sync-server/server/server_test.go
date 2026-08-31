package server

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
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
	req.Header.Set("Authorization", "Bearer testchain")
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
	req.Header.Set("Authorization", "Bearer chain-a")
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
	req2.Header.Set("Authorization", "Bearer chain-b")
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
