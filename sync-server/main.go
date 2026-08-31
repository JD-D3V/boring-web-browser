// Command sync-server runs the boring sync service.
//
//	go run . --addr :8295 --data .\data
//
// Then start the browser with:
//
//	chrome.exe --sync-url=http://localhost:8295/v1
package main

import (
	"flag"
	"log"
	"net/http"
	"time"

	"github.com/JD-D3V/boring-web-browser/sync-server/server"
	"github.com/JD-D3V/boring-web-browser/sync-server/store"
)

func main() {
	addr := flag.String("addr", ":8295", "address to listen on")
	data := flag.String("data", "data", "folder to keep the encrypted items in")
	flag.Parse()

	st, err := store.New(*data)
	if err != nil {
		log.Fatalf("could not open the store: %v", err)
	}
	srv := &http.Server{
		Addr:              *addr,
		Handler:           server.New(st).Handler(),
		ReadHeaderTimeout: 10 * time.Second,
	}
	log.Printf("boring sync server listening on %s, data in %s", *addr, *data)
	log.Fatal(srv.ListenAndServe())
}
