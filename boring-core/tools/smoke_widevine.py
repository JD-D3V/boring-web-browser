#!/usr/bin/env python3
"""Check that the browser can use Widevine.

Opens the browser with the test profile and asks the page for access to
the com.widevine.alpha key system. Prints PASS or FAIL.
"""

import sys
import time

from drive import Browser

PROFILE = r"E:\ung\testprofile"

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


def main():
    with Browser(user_data_dir=PROFILE) as b:
        b.get("https://example.com")
        result = ""
        # The CDM is registered shortly after startup, so give it a moment.
        for _ in range(15):
            result = b.run_async(CHECK)
            if result.startswith("ok:"):
                break
            time.sleep(2)
        print("key system check:", result)
        if result.startswith("ok:"):
            print("PASS: Widevine is available")
            return 0
        print("FAIL: Widevine is not available")
        return 1


if __name__ == "__main__":
    sys.exit(main())
