"""Points get_scamlist at the Chromium data files copied into boring-core/tools/data.

The scam list is checked against the public suffix list and the top sites
list. A test that builds one reads these copies whatever BORING_SRC says, so it
passes on a machine with no Chromium tree. Use as setUpModule/tearDownModule.
"""

import os
import sys
from unittest import mock

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import get_scamlist  # noqa: E402

_patches = [
    mock.patch.object(
        get_scamlist,
        "PUBLIC_SUFFIX_FILE",
        os.path.join(get_scamlist.DATA_DIR, get_scamlist.PUBLIC_SUFFIX_NAME),
    ),
    mock.patch.object(
        get_scamlist,
        "TOP_DOMAINS_FILE",
        os.path.join(get_scamlist.DATA_DIR, get_scamlist.TOP_DOMAINS_NAME),
    ),
]


def use_vendored_data():
    for patch in _patches:
        patch.start()


def stop_vendored_data():
    for patch in reversed(_patches):
        patch.stop()
