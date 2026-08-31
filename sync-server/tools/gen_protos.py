#!/usr/bin/env python3
"""Generate Go bindings for Chromium's sync protocol messages.

The sync protocol is protobuf. Rather than copy the message definitions
by hand, we generate Go code straight from Chromium's own .proto files,
the same way Brave's sync server does. Run this again after a Chromium
update so the messages stay in step.

Needs:
  - protoc, which the Chromium build already produced
  - protoc-gen-go, installed with:
      go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
"""

import argparse
import glob
import os
import subprocess
import sys

SRC = r"E:\ung\build\src"
PROTOC = os.path.join(SRC, "out", "Default", "protoc.exe")
PROTO_DIR = "components/sync/protocol"
GO_PACKAGE = "github.com/JD-D3V/boring-web-browser/sync-server/protocol"

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(HERE, "protocol")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    args = ap.parse_args()

    protoc = os.path.join(args.src, "out", "Default", "protoc.exe")
    if not os.path.exists(protoc):
        sys.exit("protoc not found at " + protoc + "; build Chromium first")

    proto_glob = os.path.join(args.src, PROTO_DIR.replace("/", os.sep), "*.proto")
    files = sorted(glob.glob(proto_glob))
    if not files:
        sys.exit("no proto files found under " + proto_glob)
    print("found", len(files), "proto files")

    os.makedirs(OUT_DIR, exist_ok=True)

    # Chromium's protos do not name a Go package, so map every one of
    # them onto ours.
    opts = ["paths=source_relative"]
    rel_names = []
    for path in files:
        rel = PROTO_DIR + "/" + os.path.basename(path)
        rel_names.append(rel)
        opts.append("M" + rel + "=" + GO_PACKAGE)

    # Some protos use google/protobuf/descriptor.proto, which lives in
    # the bundled protobuf copy.
    well_known = os.path.join(args.src, "third_party", "protobuf", "src")

    cmd = [protoc, "--proto_path=" + args.src,
           "--proto_path=" + well_known,
           "--go_out=" + OUT_DIR,
           "--go_opt=" + ",".join(opts)] + rel_names
    print("running protoc ...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)

    # protoc writes into a nested folder that matches the proto path.
    nested = os.path.join(OUT_DIR, *PROTO_DIR.split("/"))
    if os.path.isdir(nested):
        for name in os.listdir(nested):
            os.replace(os.path.join(nested, name),
                       os.path.join(OUT_DIR, name))
        # Remove the now empty folders.
        for root, dirs, _files in os.walk(os.path.join(OUT_DIR, "components"),
                                          topdown=False):
            os.rmdir(root)
    count = len([f for f in os.listdir(OUT_DIR) if f.endswith(".pb.go")])
    print("wrote", count, "Go files into", OUT_DIR)


if __name__ == "__main__":
    main()
