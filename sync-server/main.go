// Command sync-server runs the boring sync service.
//
//	go run . --data .\data
//
// Then start the browser with:
//
//	chrome.exe --sync-url=http://localhost:8295/v1
//
// It listens on 127.0.0.1 by default. Serving other machines needs TLS,
// because every request carries the bearer token that guards a chain:
//
//	go run . --addr :8295 --tls-cert cert.pem --tls-key key.pem
//
// Each device must send that token as "Authorization: Bearer <token>".
// The server hashes it to decide which chain the request belongs to, so
// two devices sharing a chain must send exactly the same token, and a
// request without one is refused.
package main

import (
	"flag"
	"log"
	"net"
	"net/http"
	"time"

	"github.com/JD-D3V/boring-web-browser/sync-server/server"
	"github.com/JD-D3V/boring-web-browser/sync-server/store"
)

// loopback reports whether the listen address stays on this machine.
// Anything else is reachable by other people, and the bearer token that
// guards a sync chain must not cross a network in the clear.
func loopback(addr string) bool {
	host, _, err := net.SplitHostPort(addr)
	if err != nil {
		return false
	}
	switch host {
	case "localhost":
		return true
	case "":
		// A bare ":8295" listens on every interface.
		return false
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func main() {
	addr := flag.String("addr", "127.0.0.1:8295", "address to listen on")
	data := flag.String("data", "data", "folder to keep the encrypted items in")
	cert := flag.String("tls-cert", "", "TLS certificate file")
	key := flag.String("tls-key", "", "TLS private key file")
	insecure := flag.Bool("insecure", false,
		"allow serving without TLS on an address other people can reach")
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

	useTLS := *cert != "" && *key != ""
	if !useTLS && !loopback(*addr) && !*insecure {
		log.Fatalf("refusing to serve %s without TLS: the bearer token "+
			"would cross the network in the clear. Pass --tls-cert and "+
			"--tls-key, listen on 127.0.0.1, or pass --insecure if you "+
			"have your own TLS in front.", *addr)
	}

	if useTLS {
		log.Printf("boring sync server listening on %s over TLS, data in %s",
			*addr, *data)
		log.Fatal(srv.ListenAndServeTLS(*cert, *key))
	}
	log.Printf("boring sync server listening on %s, data in %s", *addr, *data)
	log.Fatal(srv.ListenAndServe())
}
