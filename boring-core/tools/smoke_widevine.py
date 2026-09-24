#!/usr/bin/env python3
"""Check that the browser's DRM playback matches what the build claims.

Widevine support is compiled in, but the CDM is a separate proprietary
binary Chrome fetches from Google at run time. We do not talk to that
service and `check_package.py` refuses to ship the CDM, so a downloaded
copy has none. v1 declares that in
`components/boring/core/boring_capabilities.h` as
`kDrmPlaybackAvailable = false`.

This test reads that declaration and checks it **in both directions**,
which is why it is not a skip:

  declared available    the key system must work, or this fails
  declared unavailable  the key system must NOT work. A CDM that turned
                        up anyway is reported as a failure too, because
                        it means the browser can do something we told
                        people it cannot, and something we are not
                        licensed to distribute.

Exit 0 pass, 1 fail, 3 not applicable (declared unavailable, and
confirmed unavailable).
"""

import os
import re
import sys
import time

from drive import Browser, PROFILE

# One source of truth for what this build claims, read from the header
# the browser itself compiles, so the test and the browser cannot
# disagree about it.
CAPABILITIES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "components", "boring", "core", "boring_capabilities.h",
)

# Told apart from a real failure by smoke_all.py, which reports it as
# "n/a" rather than counting it as a pass.
NOT_APPLICABLE = 3

CHECK = """
var done = arguments[0];
navigator.requestMediaKeySystemAccess('com.widevine.alpha', [{
  initDataTypes: ['cenc'],
  videoCapabilities: [{contentType: 'video/mp4; codecs="avc1.42E01E"'}]
}]).then(function(access) {
  done('ok:' + access.keySystem);
}, function(err) {
  done('error:' + err.name + ':' + err.message);
});
"""


def drm_declared_available():
    """What the build says about DRM playback."""
    with open(CAPABILITIES, encoding="utf-8") as f:
        text = f.read()
    match = re.search(r"kDrmPlaybackAvailable\s*=\s*(true|false)\s*;", text)
    if not match:
        raise SystemExit(
            "smoke_widevine: kDrmPlaybackAvailable not found in " + CAPABILITIES
        )
    return match.group(1) == "true"


def ask_browser(attempts):
    """Whether the Widevine key system answers, and what it said."""
    with Browser(user_data_dir=PROFILE) as b:
        b.get("https://example.com")
        result = ""
        for _ in range(attempts):
            result = b.run_async(CHECK)
            if result.startswith("ok:"):
                return True, result
            time.sleep(2)
        return False, result


def main():
    declared = drm_declared_available()

    # A build that says it has DRM gets the long wait, because the CDM
    # registers a moment after startup. A build that says it has none
    # only has to be given a fair chance to prove otherwise.
    works, result = ask_browser(15 if declared else 5)
    print("key system check:", result)

    if declared:
        if works:
            print("PASS: Widevine is available, as this build claims")
            return 0
        print("FAIL: this build claims DRM playback and Widevine is not available")
        return 1

    if works:
        print(
            "FAIL: Widevine works, but this build declares "
            "kDrmPlaybackAvailable = false. Either a CDM reached a build that "
            "must not ship one, or the declaration is now wrong"
        )
        return 1
    print(
        "n/a: DRM playback is out of scope for v1 and is confirmed absent. "
        "No CDM ships and none can be fetched, so Widevine content will not "
        "play. See components/boring/core/boring_capabilities.h"
    )
    return NOT_APPLICABLE


if __name__ == "__main__":
    sys.exit(main())
