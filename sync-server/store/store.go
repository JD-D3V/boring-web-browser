// Package store keeps the encrypted sync items.
//
// Everything here is opaque. An item is a blob the browser encrypted
// before sending, plus the small amount of routing information the sync
// protocol needs: which chain it belongs to, its id, its type, and a
// version number that only ever goes up.
package store

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sort"
	"sync"
)

// Item is one synced thing, for example a bookmark or a password.
// Specifics holds the encrypted payload exactly as the browser sent it.
type Item struct {
	ID        string `json:"id"`
	ParentID  string `json:"parent_id,omitempty"`
	Name      string `json:"name,omitempty"`
	Version   int64  `json:"version"`
	DataType  int32  `json:"data_type"`
	Deleted   bool   `json:"deleted,omitempty"`
	Folder    bool   `json:"folder,omitempty"`
	Specifics []byte `json:"specifics"`
	Ctime     int64  `json:"ctime,omitempty"`
	Mtime     int64  `json:"mtime,omitempty"`
}

// ErrNotFound is returned when a chain has never been written to.
var ErrNotFound = errors.New("chain not found")

// Store holds every chain. A chain is one person's set of devices.
type Store struct {
	mu   sync.Mutex
	dir  string
	data map[string]*chain
}

type chain struct {
	Birthday string           `json:"birthday"`
	Version  int64            `json:"version"`
	Items    map[string]*Item `json:"items"`
}

// New opens a store kept in dir. An empty dir keeps everything in
// memory only, which is what the tests use.
func New(dir string) (*Store, error) {
	s := &Store{dir: dir, data: map[string]*chain{}}
	if dir == "" {
		return s, nil
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	names, err := filepath.Glob(filepath.Join(dir, "*.json"))
	if err != nil {
		return nil, err
	}
	for _, name := range names {
		raw, err := os.ReadFile(name)
		if err != nil {
			return nil, err
		}
		c := &chain{Items: map[string]*Item{}}
		if err := json.Unmarshal(raw, c); err != nil {
			return nil, err
		}
		id := filepath.Base(name)
		s.data[id[:len(id)-len(".json")]] = c
	}
	return s, nil
}

func (s *Store) chainLocked(id string) *chain {
	c, ok := s.data[id]
	if !ok {
		c = &chain{Items: map[string]*Item{}}
		s.data[id] = c
	}
	return c
}

func (s *Store) saveLocked(id string) error {
	if s.dir == "" {
		return nil
	}
	raw, err := json.Marshal(s.data[id])
	if err != nil {
		return err
	}
	// Write to a temporary file first so a crash cannot leave a half
	// written chain behind.
	path := filepath.Join(s.dir, id+".json")
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// Birthday returns the id of this chain's data. When a chain is reset,
// it gets a new birthday, and clients that still hold the old one know
// to start over.
func (s *Store) Birthday(chainID string) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.chainLocked(chainID).Birthday
}

// SetBirthday records a new birthday for a chain.
func (s *Store) SetBirthday(chainID, birthday string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := s.chainLocked(chainID)
	c.Birthday = birthday
	return s.saveLocked(chainID)
}

// Commit writes items and gives each a new version number. It returns
// the stored items, in the same order they were given.
func (s *Store) Commit(chainID string, items []*Item) ([]*Item, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := s.chainLocked(chainID)
	out := make([]*Item, 0, len(items))
	for _, in := range items {
		c.Version++
		stored := *in
		stored.Version = c.Version
		c.Items[stored.ID] = &stored
		copied := stored
		out = append(out, &copied)
	}
	if err := s.saveLocked(chainID); err != nil {
		return nil, err
	}
	return out, nil
}

// Updates returns every item of the given types newer than sinceVersion,
// oldest first, along with the chain's current version.
func (s *Store) Updates(chainID string, sinceVersion int64,
	types map[int32]bool, limit int) ([]*Item, int64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := s.chainLocked(chainID)
	var out []*Item
	for _, item := range c.Items {
		if item.Version <= sinceVersion {
			continue
		}
		if len(types) > 0 && !types[item.DataType] {
			continue
		}
		copied := *item
		out = append(out, &copied)
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].Version < out[j].Version
	})
	if limit > 0 && len(out) > limit {
		out = out[:limit]
	}
	return out, c.Version
}

// Version is the chain's newest version number.
func (s *Store) Version(chainID string) int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.chainLocked(chainID).Version
}

// Clear throws away everything in a chain. Used when a person asks to
// reset sync from one of their devices.
func (s *Store) Clear(chainID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := s.chainLocked(chainID)
	c.Items = map[string]*Item{}
	c.Version = 0
	c.Birthday = ""
	return s.saveLocked(chainID)
}
