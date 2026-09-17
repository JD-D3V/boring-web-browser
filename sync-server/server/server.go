// Package server answers the browser's sync requests.
//
// The browser posts a protobuf ClientToServerMessage and expects a
// ClientToServerResponse back. Two kinds matter: Commit, which sends
// changes up, and GetUpdates, which pulls changes down. Everything the
// browser sends inside an entry is already encrypted, so this code just
// moves opaque bytes around.
package server

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"log"
	"net/http"
	"strings"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	pb "github.com/JD-D3V/boring-web-browser/sync-server/protocol"
	"github.com/JD-D3V/boring-web-browser/sync-server/store"
)

// How many items we send back at once. The browser asks again for the
// rest, so this only limits the size of one reply.
const maxBatch = 500

// Server handles sync requests for every chain.
type Server struct {
	store *store.Store
}

// New returns a server that keeps its chains in s.
func New(s *store.Store) *Server {
	return &Server{store: s}
}

// Handler returns the routes to serve.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/command/", s.handleCommand)
	mux.HandleFunc("/v1/health", func(w http.ResponseWriter, _ *http.Request) {
		// A failed write means the caller hung up. There is nobody left
		// to tell.
		_, _ = w.Write([]byte("ok"))
	})
	return mux
}

// The shortest bearer token we will accept. The token is the only
// thing standing between one person's chain and everyone else's, so a
// short one is refused rather than quietly trusted.
const minTokenLength = 16

// ErrNoToken is returned when a request carries no usable bearer token.
var ErrNoToken = errors.New("missing or too short bearer token")

// chainID works out which sync chain this request belongs to. The
// browser sends a bearer token that the devices in one chain share.
//
// The token is a secret, so it is never used as a name directly. We
// hash it and use the digest instead. That buys three things: a fixed
// length, file name safe id; no way for two different tokens to land on
// the same chain; and the raw token never reaches the disk.
//
// A request without a usable token gets no chain at all. There is
// deliberately no shared fallback chain: an unauthenticated request
// must not be able to read or write anybody's data.
func chainID(r *http.Request) (string, error) {
	auth := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if len(auth) <= len(prefix) || !strings.EqualFold(auth[:len(prefix)], prefix) {
		return "", ErrNoToken
	}
	token := strings.TrimSpace(auth[len(prefix):])
	if len(token) < minTokenLength {
		return "", ErrNoToken
	}
	// Hashing the whole token means every distinct token gets its own
	// chain. The old scheme stripped punctuation and truncated, so
	// "alice.1" and "alice1" collided into one chain.
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:]), nil
}

func newBirthday() string {
	buf := make([]byte, 16)
	if _, err := rand.Read(buf); err != nil {
		return "boring"
	}
	return hex.EncodeToString(buf)
}

func (s *Server) handleCommand(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "post only", http.StatusMethodNotAllowed)
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 32<<20))
	if err != nil {
		http.Error(w, "could not read body", http.StatusBadRequest)
		return
	}
	msg := &pb.ClientToServerMessage{}
	if err := proto.Unmarshal(body, msg); err != nil {
		http.Error(w, "could not read message", http.StatusBadRequest)
		return
	}

	id, err := chainID(r)
	if err != nil {
		// No token, no data. Say so plainly and send nothing back.
		w.Header().Set("WWW-Authenticate", "Bearer")
		http.Error(w, "a bearer token is required", http.StatusUnauthorized)
		return
	}

	birthday := s.store.Birthday(id)
	if birthday == "" {
		birthday = newBirthday()
		if err := s.store.SetBirthday(id, birthday); err != nil {
			http.Error(w, "storage error", http.StatusInternalServerError)
			return
		}
	}

	resp := &pb.ClientToServerResponse{
		StoreBirthday: proto.String(birthday),
		ErrorCode:     pb.SyncEnums_SUCCESS.Enum(),
	}

	// A client holding an old birthday must start over. This is how a
	// reset from one device reaches the others.
	if given := msg.GetStoreBirthday(); given != "" && given != birthday {
		resp.ErrorCode = pb.SyncEnums_NOT_MY_BIRTHDAY.Enum()
		writeResponse(w, resp)
		return
	}

	switch msg.GetMessageContents() {
	case pb.ClientToServerMessage_COMMIT:
		resp.Commit = s.commit(id, msg.GetCommit())
	case pb.ClientToServerMessage_GET_UPDATES:
		resp.GetUpdates = s.getUpdates(id, msg.GetGetUpdates())
	case pb.ClientToServerMessage_CLEAR_SERVER_DATA:
		if err := s.store.Clear(id); err != nil {
			http.Error(w, "storage error", http.StatusInternalServerError)
			return
		}
		resp.ClearServerData = &pb.ClearServerDataResponse{}
	default:
		resp.ErrorCode = pb.SyncEnums_UNKNOWN.Enum()
		resp.ErrorMessage = proto.String("unsupported message type")
	}

	writeResponse(w, resp)
}

func writeResponse(w http.ResponseWriter, resp *pb.ClientToServerResponse) {
	out, err := proto.Marshal(resp)
	if err != nil {
		http.Error(w, "could not write reply", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/octet-stream")
	if _, err := w.Write(out); err != nil {
		log.Printf("could not send reply: %v", err)
	}
}

func (s *Server) commit(id string, msg *pb.CommitMessage) *pb.CommitResponse {
	resp := &pb.CommitResponse{}
	if msg == nil {
		return resp
	}
	items := make([]*store.Item, 0, len(msg.GetEntries()))
	for _, entry := range msg.GetEntries() {
		specifics, err := proto.Marshal(entry.GetSpecifics())
		if err != nil {
			specifics = nil
		}
		items = append(items, &store.Item{
			ID:        entry.GetIdString(),
			ParentID:  entry.GetParentIdString(),
			Name:      entry.GetName(),
			DataType:  dataTypeOf(entry),
			Deleted:   entry.GetDeleted(),
			Folder:    entry.GetFolder(),
			Specifics: specifics,
			Ctime:     entry.GetCtime(),
			Mtime:     entry.GetMtime(),
		})
	}
	stored, err := s.store.Commit(id, items)
	if err != nil {
		log.Printf("commit failed: %v", err)
		for range items {
			resp.Entryresponse = append(resp.Entryresponse,
				&pb.CommitResponse_EntryResponse{
					ResponseType: pb.CommitResponse_TRANSIENT_ERROR.Enum(),
				})
		}
		return resp
	}
	for _, item := range stored {
		resp.Entryresponse = append(resp.Entryresponse,
			&pb.CommitResponse_EntryResponse{
				ResponseType: pb.CommitResponse_SUCCESS.Enum(),
				IdString:     proto.String(item.ID),
				Version:      proto.Int64(item.Version),
			})
	}
	return resp
}

func (s *Server) getUpdates(id string,
	msg *pb.GetUpdatesMessage) *pb.GetUpdatesResponse {
	resp := &pb.GetUpdatesResponse{}
	if msg == nil {
		return resp
	}

	// Each data type carries its own position, held in the token the
	// server handed out last time. The lowest one decides where this
	// batch starts.
	types := map[int32]bool{}
	var since int64 = -1
	for _, marker := range msg.GetFromProgressMarker() {
		types[marker.GetDataTypeId()] = true
		version := versionFromToken(marker.GetToken())
		if since < 0 || version < since {
			since = version
		}
	}
	if since < 0 {
		since = 0
	}

	items, current := s.store.Updates(id, since, types, maxBatch)
	for _, item := range items {
		specifics := &pb.EntitySpecifics{}
		if len(item.Specifics) > 0 {
			if err := proto.Unmarshal(item.Specifics, specifics); err != nil {
				log.Printf("skipping unreadable item %s: %v", item.ID, err)
				continue
			}
		}
		resp.Entries = append(resp.Entries, &pb.SyncEntity{
			IdString:       proto.String(item.ID),
			ParentIdString: proto.String(item.ParentID),
			Name:           proto.String(item.Name),
			Version:        proto.Int64(item.Version),
			Deleted:        proto.Bool(item.Deleted),
			Folder:         proto.Bool(item.Folder),
			Specifics:      specifics,
			Ctime:          proto.Int64(item.Ctime),
			Mtime:          proto.Int64(item.Mtime),
		})
	}

	// Tell the client how far it has now read, per type.
	reached := current
	if len(items) == maxBatch {
		reached = items[len(items)-1].Version
	}
	for _, marker := range msg.GetFromProgressMarker() {
		resp.NewProgressMarker = append(resp.NewProgressMarker,
			&pb.DataTypeProgressMarker{
				DataTypeId: proto.Int32(marker.GetDataTypeId()),
				Token:      tokenFromVersion(reached),
			})
	}
	remaining := current - reached
	if remaining < 0 {
		remaining = 0
	}
	resp.ChangesRemaining = proto.Int64(remaining)
	return resp
}

// dataTypeOf works out which kind of thing an entry is by looking at
// which specifics field is filled in. The field number in the specifics
// message is the data type id the protocol uses.
func dataTypeOf(entry *pb.SyncEntity) int32 {
	specifics := entry.GetSpecifics()
	if specifics == nil {
		return 0
	}
	var found int32
	specifics.ProtoReflect().Range(
		func(fd protoreflect.FieldDescriptor, _ protoreflect.Value) bool {
			found = int32(fd.Number())
			return false
		})
	return found
}
