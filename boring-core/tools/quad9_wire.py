"""DNS wire messages for the Quad9 block warning tests.

Shared by tests/test_quad9_answer.py and smoke_dns_warning.py. The blocked
answer is a real one captured from Quad9 (tests/quad9_captures.json); only
the name in it is swapped, so a made up name can stand in for a threat list
name and no real one is ever used.
"""

import base64
import json
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURES = os.path.join(HERE, "tests", "quad9_captures.json")


def captures():
    """key -> raw bytes of each captured answer."""
    with open(CAPTURES, encoding="utf-8") as f:
        data = json.load(f)["captures"]
    return {k: bytes.fromhex(v["wire_hex"]) for k, v in data.items()}


def encode_name(name):
    out = b""
    for label in name.rstrip(".").split("."):
        out += bytes([len(label)]) + label.encode("ascii")
    return out + b"\0"


def read_question(message):
    """(name, end offset of the question) of a query or an uncompressed
    answer."""
    pos = 12
    labels = []
    while message[pos]:
        n = message[pos]
        labels.append(message[pos + 1 : pos + 1 + n].decode("ascii"))
        pos += n + 1
    return ".".join(labels), pos + 1 + 4


def decode_get_query(dns_param):
    """The query message from the ?dns= value of a DoH GET."""
    padded = dns_param + "=" * (-len(dns_param) % 4)
    return base64.urlsafe_b64decode(padded)


def with_name(answer, name):
    """The captured `answer` asking about `name` instead of the name in it.
    Only for answers whose question is the first thing after the header and
    that point nowhere into it (the blocked one)."""
    old, end = read_question(answer)
    start = 12
    return answer[:start] + encode_name(name) + answer[end - 4 :]


def blocked_answer(name):
    return with_name(captures()["blocked"], name)


def not_found_answer(name):
    """A real "does not exist": NXDOMAIN with an SOA record, no EDE."""
    question = encode_name(name) + struct.pack(">HH", 1, 1)
    soa_data = (
        encode_name("ns." + name)
        + encode_name("hostmaster." + name)
        + struct.pack(">IIIII", 1, 3600, 600, 86400, 900)
    )
    soa = encode_name(name) + struct.pack(">HHIH", 6, 1, 900, len(soa_data)) + soa_data
    header = struct.pack(">HHHHHH", 0, 0x8183, 1, 0, 1, 0)
    return header + question + soa


def address_answer(name, ip="127.0.0.1"):
    """NOERROR with one A record."""
    question = encode_name(name) + struct.pack(">HH", 1, 1)
    rdata = bytes(int(p) for p in ip.split("."))
    record = encode_name(name) + struct.pack(">HHIH", 1, 1, 60, 4) + rdata
    header = struct.pack(">HHHHHH", 0, 0x8180, 1, 1, 0, 0)
    return header + question + record
