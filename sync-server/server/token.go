package server

import "strconv"

// The progress token is the protocol's way of remembering how far a
// device has read. The browser treats it as opaque bytes, so we simply
// store the version number in it as text.

func tokenFromVersion(version int64) []byte {
	return []byte(strconv.FormatInt(version, 10))
}

func versionFromToken(token []byte) int64 {
	if len(token) == 0 {
		return 0
	}
	version, err := strconv.ParseInt(string(token), 10, 64)
	if err != nil || version < 0 {
		return 0
	}
	return version
}
