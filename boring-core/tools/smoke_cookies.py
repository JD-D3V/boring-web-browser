#!/usr/bin/env python3
"""Check "block cookie banners": the switch, the cookie list, and the
banners the browser answers with reject.

Two kinds of local page. One shows a banner that only the test cookie
list names, plus an element the main test list hides, which proves the
engine is running whatever happens to the banner. The others are
banners built the way six consent platforms build theirs (OneTrust,
Cookiebot, TrustArc, Quantcast, Didomi and Usercentrics), each with a
reject button and an accept button that record which was pressed.
The markup is ours, written from what those platforms ship; no live
site is touched. Checked:

  - on by default: the list's banner is hidden and the switch on the
    Protection page is on
  - every platform banner is answered with reject, never accept, also
    one drawn late and one that has no reject button on the banner
  - a banner no rule knows is hidden and never accepted
  - a visitor who answered before (the platform's cookie) is left alone
  - turned off from the page: saved in the profile, and after a
    restart the list's banner shows and no platform banner is answered
  - turned on again, with blocking off for one site: that site's
    banner is left alone and the other site's is still answered

Whether a change applies to pages without a restart is printed as a
NOTE, not counted: it depends on when the engine reads the pref.

Usage: python smoke_cookies.py
"""

import sys
import tempfile

from drive import Browser
from smoke_local import (
    HTML,
    OTHER_SITE,
    TEST_SITE,
    THIRD_PARTY,
    Checks,
    Pages,
    browser_args,
    get_profile_pref,
    hidden_expr,
    list_folder,
    set_profile_pref,
    shown_expr,
    wait_for,
)

PREF = "boring.privacy.block_cookie_banners"
OFF_SITES_PREF = "boring.blocking_off_sites"

LISTS = {
    "easylist.txt": (
        "[Adblock Plus 2.0]\n! Title: boring cookie smoke test\n##.boring-control-ad\n"
    ),
    "ubo.txt": "! Title: boring cookie smoke test, nothing here\n",
    "cookies.txt": (
        "[Adblock Plus 2.0]\n"
        "! Title: boring cookie smoke test, cookie rules\n"
        "##.boring-cookie-banner\n"
        f"{TEST_SITE}###boring-cookie-dialog\n"
    ),
}

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>cookie test</title>
<h1>cookie test</h1>
<div class="boring-control-ad">control ad</div>
<div class="boring-cookie-banner">We use cookies. <button>Accept</button></div>
<div id="boring-cookie-dialog">Cookie settings</div>
<p id="content">The article.</p>
"""

BANNER = ".boring-cookie-banner"
DIALOG = "#boring-cookie-dialog"

# What every platform page does with a click: note the answer, then take
# the banner down, as the real thing does.
COMMON_SCRIPT = """
window.__answer = null;
function onAnswer(e) {
  var t = e.target.closest && e.target.closest('[data-answer]');
  if (!t) return;
  window.__answer = t.getAttribute('data-answer');
  var gone = document.querySelectorAll('[data-banner]');
  for (var i = 0; i < gone.length; i++) gone[i].style.display = 'none';
}
document.addEventListener('click', onAnswer, true);
"""


def page(body, script=""):
    return (
        '<!doctype html><meta charset="utf-8"><title>consent test</title>'
        "<h1>consent test</h1><p id='content'>The article.</p>"
        f"{body}<script>{COMMON_SCRIPT}{script}</script>"
    )


# name: (page, the banner's selector for "is it showing")
PLATFORMS = {
    "onetrust": (
        page(
            '<div id="onetrust-consent-sdk"><div id="onetrust-banner-sdk" data-banner>'
            "<p>We value your privacy</p>"
            '<button id="onetrust-pc-btn-handler">Cookie Settings</button>'
            '<button id="onetrust-reject-all-handler" data-answer="reject">Reject All</button>'
            '<button id="onetrust-accept-btn-handler" data-answer="accept">Accept All</button>'
            "</div></div>"
        ),
        "#onetrust-banner-sdk",
    ),
    # No reject button on the banner: the settings have to be opened,
    # the categories switched off and the choice saved.
    "onetrust-settings": (
        page(
            '<div id="onetrust-consent-sdk"><div id="onetrust-banner-sdk" data-banner>'
            "<p>We value your privacy</p>"
            '<button id="onetrust-pc-btn-handler">Cookie Settings</button>'
            '<button id="onetrust-accept-btn-handler" data-answer="accept">Accept All</button>'
            '</div><div id="onetrust-pc-sdk" style="display:none"></div></div>',
            """
document.getElementById('onetrust-pc-btn-handler').addEventListener('click', function() {
  setTimeout(function() {
    var pc = document.getElementById('onetrust-pc-sdk');
    pc.style.display = 'block';
    pc.innerHTML = '<label><input type="checkbox" class="category-switch-handler" checked> Analytics</label>' +
      '<label><input type="checkbox" class="category-switch-handler" checked> Ads</label>' +
      '<label><input type="checkbox" class="category-switch-handler" checked disabled> Necessary</label>' +
      '<button class="save-preference-btn-handler">Confirm My Choices</button>';
    pc.querySelector('.save-preference-btn-handler').addEventListener('click', function() {
      var on = pc.querySelectorAll('input.category-switch-handler:checked:not(:disabled)').length;
      window.__answer = on === 0 ? 'reject' : 'partial';
      document.getElementById('onetrust-banner-sdk').style.display = 'none';
      pc.style.display = 'none';
    });
  }, 300);
});
""",
        ),
        "#onetrust-banner-sdk",
    ),
    "cookiebot": (
        page(
            '<div id="CybotCookiebotDialog" data-banner><p>This website uses cookies</p>'
            '<button id="CybotCookiebotDialogBodyButtonDecline" data-answer="reject">Deny</button>'
            '<button id="CybotCookiebotDialogBodyLevelButtonLevelOptinAllowallSelection" data-answer="selection">Allow selection</button>'
            '<button id="CybotCookiebotDialogBodyButtonAccept" data-answer="accept">Allow all</button>'
            "</div>"
        ),
        "#CybotCookiebotDialog",
    ),
    "trustarc": (
        page(
            '<div id="truste-consent-track" data-banner><p>We use cookies</p>'
            '<button id="truste-consent-required" data-answer="reject">Required cookies only</button>'
            '<button id="truste-consent-button" data-answer="accept">Accept all</button>'
            "</div>"
        ),
        "#truste-consent-track",
    ),
    "quantcast": (
        page(
            '<div id="qc-cmp2-container" data-banner><div class="qc-cmp2-summary-buttons">'
            '<button mode="secondary" data-answer="more">More options</button>'
            '<button mode="secondary" data-answer="reject">Disagree</button>'
            '<button mode="primary" data-answer="accept">Agree</button>'
            "</div></div>"
        ),
        "#qc-cmp2-container",
    ),
    # No reject on the first screen: "More options" opens a second one
    # with a switch per purpose and a save button.
    "quantcast-more": (
        page(
            '<div id="qc-cmp2-container" data-banner><div class="qc-cmp2-summary-buttons">'
            '<button mode="secondary" id="qc-more">More options</button>'
            '<button mode="primary" data-answer="accept">Agree</button>'
            '</div><div id="qc-second"></div></div>',
            """
document.getElementById('qc-more').addEventListener('click', function() {
  setTimeout(function() {
    var second = document.getElementById('qc-second');
    second.innerHTML = '<div class="qc-cmp2-toggle-switch"><button aria-checked="true"></button></div>' +
      '<div class="qc-cmp2-toggle-switch"><button aria-checked="true"></button></div>' +
      '<div class="qc-cmp2-buttons-desktop"><button mode="secondary">Cancel</button>' +
      '<button mode="primary" id="qc-save">Save &amp; Exit</button></div>';
    var toggles = second.querySelectorAll('.qc-cmp2-toggle-switch > button');
    for (var i = 0; i < toggles.length; i++) {
      toggles[i].addEventListener('click', function(e) {
        e.target.setAttribute('aria-checked',
            e.target.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
      });
    }
    document.getElementById('qc-save').addEventListener('click', function() {
      var on = second.querySelectorAll('button[aria-checked="true"]').length;
      window.__answer = on === 0 ? 'reject' : 'partial';
      document.getElementById('qc-cmp2-container').style.display = 'none';
    });
  }, 300);
});
""",
        ),
        "#qc-cmp2-container",
    ),
    "didomi": (
        page(
            '<div id="didomi-host" data-banner><div id="didomi-notice">'
            '<button id="didomi-notice-disagree-button" data-answer="reject">Disagree</button>'
            '<button id="didomi-notice-agree-button" data-answer="accept">Agree</button>'
            "</div></div>"
        ),
        "#didomi-host",
    ),
    # The buttons are inside an open shadow root, as Usercentrics draws them.
    "usercentrics": (
        page(
            '<div id="usercentrics-root" data-banner></div>',
            """
var host = document.getElementById('usercentrics-root');
var shadow = host.attachShadow({mode: 'open'});
shadow.innerHTML = '<div>We use cookies' +
  '<button data-testid="uc-deny-all-button" data-answer="reject">Deny</button>' +
  '<button data-testid="uc-accept-all-button" data-answer="accept">Accept all</button></div>';
shadow.addEventListener('click', onAnswer, true);
""",
        ),
        "#usercentrics-root",
    ),
}

# A platform banner that the page draws a moment after load, as most do.
LATE = page(
    "",
    """
setTimeout(function() {
  document.body.insertAdjacentHTML('beforeend',
    '<div id="CybotCookiebotDialog" data-banner>Cookies' +
    '<button id="CybotCookiebotDialogBodyButtonDecline" data-answer="reject">Deny</button>' +
    '<button id="CybotCookiebotDialogBodyButtonAccept" data-answer="accept">Allow all</button></div>');
}, 1500);
""",
)

# A banner of a platform no rule knows: only the cookie list can hide it.
UNKNOWN = page(
    '<div class="boring-cookie-banner" data-banner>We use cookies. '
    '<button data-answer="accept">Accept</button></div>'
)

# OneTrust's own cookie, set before the banner is drawn: the visitor has
# answered already, so nothing is pressed.
ANSWERED = page(
    '<div id="onetrust-banner-sdk" data-banner>We value your privacy'
    '<button id="onetrust-reject-all-handler" data-answer="reject">Reject All</button></div>',
    "document.cookie = 'OptanonAlertBoxClosed=2026-10-28T10:00:00; path=/';",
)

PAGES = {
    "/page.html": (PAGE, HTML),
    "/late.html": (LATE, HTML),
    "/unknown.html": (UNKNOWN, HTML),
    "/answered.html": (ANSWERED, HTML),
    **{f"/{name}.html": (html, HTML) for name, (html, _) in PLATFORMS.items()},
}


def engine_running(b):
    """True once the main list hides its control element."""
    return wait_for(b, hidden_expr(".boring-control-ad"), timeout_ms=30000)


def banner_state(b, want_hidden, timeout_ms=5000):
    """True when both list banners are hidden (or both shown)."""
    expr = hidden_expr if want_hidden else shown_expr
    return wait_for(b, f"{expr(BANNER)} && {expr(DIALOG)}", timeout_ms=timeout_ms)


def open_switch(b):
    b.get("chrome://boring-protection")
    return wait_for(b, "!!document.getElementById('hide-cookies')")


def answer_of(b):
    return b.run("return window.__answer")


def answered(b, want, timeout_ms=10000):
    return wait_for(b, f"window.__answer === {want!r}", timeout_ms=timeout_ms)


def untouched(b, banner, timeout_ms=4000):
    """True when the banner is still showing and nothing pressed it."""
    return not wait_for(b, "window.__answer !== null", timeout_ms) and b.run(
        f"return {shown_expr(banner)}"
    )


def main():
    check = Checks()
    pages = Pages(PAGES)

    def url(host, name):
        return pages.url(host, f"/{name}.html")

    try:
        with (
            list_folder(LISTS) as lists,
            tempfile.TemporaryDirectory(prefix="cookies-") as profile,
        ):
            args = browser_args(lists)

            # On by default.
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(url(TEST_SITE, "page"))
                check("the engine is running", engine_running(b))
                check(
                    "on by default, the list's banner is hidden",
                    banner_state(b, want_hidden=True, timeout_ms=10000),
                )
                check(
                    "the article itself stays",
                    b.run(f"return {shown_expr('#content')}"),
                )

                check("the Protection page has the switch", open_switch(b))
                control = b.run(
                    "var e = document.getElementById('hide-cookies');"
                    "var l = document.querySelector('label[for=hide-cookies]');"
                    "return {type: e.type, checked: e.checked,"
                    " label: l ? l.textContent.trim().toLowerCase() : ''}"
                )
                check(
                    "it is a real checkbox, on, labelled for cookies",
                    control["type"] == "checkbox"
                    and control["checked"] is True
                    and "cookie" in control["label"],
                    str(control),
                )

                for name in PLATFORMS:
                    b.get(url(TEST_SITE, name))
                    check(
                        f"{name}: answered with reject",
                        answered(b, "reject"),
                        f"answer was {answer_of(b)!r}",
                    )
                    check(
                        f"{name}: the banner is gone",
                        b.run(f"return !{shown_expr(PLATFORMS[name][1])}"),
                    )

                b.get(url(TEST_SITE, "late"))
                check(
                    "a banner drawn late is answered with reject", answered(b, "reject")
                )

                b.get(url(TEST_SITE, "unknown"))
                check(
                    "a banner no rule knows is hidden",
                    wait_for(b, hidden_expr(BANNER), 8000),
                )
                check(
                    "and never accepted",
                    not wait_for(b, "window.__answer !== null", 3000),
                )

                b.get(url(THIRD_PARTY, "answered"))
                check(
                    "a visitor who answered before is left alone",
                    untouched(b, "#onetrust-banner-sdk"),
                )
                b.run("document.cookie = 'OptanonAlertBoxClosed=; Max-Age=0; path=/'")

                # Turn it off from the page.
                check("the switch opens again", open_switch(b))
                b.run("document.getElementById('hide-cookies').click()")
                check(
                    "the switch turns off",
                    wait_for(b, "!document.getElementById('hide-cookies').checked"),
                )

                # Not counted: see the docstring.
                b.get(url(TEST_SITE, "onetrust"))
                live = wait_for(b, "window.__answer === 'reject'", 4000)
                print(
                    "NOTE: without a restart a banner is "
                    + ("still answered" if live else "left alone")
                )

            check("turning it off is saved", get_profile_pref(profile, PREF) is False)

            # Off: nothing hidden, nothing answered.
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(url(TEST_SITE, "page"))
                check("the engine is running after a restart", engine_running(b))
                check(
                    "with the switch off, the list's banner shows",
                    not wait_for(
                        b, f"{hidden_expr(BANNER)} || {hidden_expr(DIALOG)}", 4000
                    ),
                )
                for name in PLATFORMS:
                    b.get(url(TEST_SITE, name))
                    check(
                        f"{name}: with the switch off, the banner shows and is not answered",
                        untouched(b, PLATFORMS[name][1], timeout_ms=3000),
                    )
                check(
                    "the switch shows off",
                    open_switch(b)
                    and b.run(
                        "return !document.getElementById('hide-cookies').checked"
                    ),
                )
                b.run("document.getElementById('hide-cookies').click()")
                check(
                    "the switch turns on again",
                    wait_for(b, "document.getElementById('hide-cookies').checked"),
                )

            check("turning it on is saved", get_profile_pref(profile, PREF) is True)

            # On, with blocking off for one site: that site is left alone.
            set_profile_pref(profile, OFF_SITES_PREF, [OTHER_SITE])
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(url(TEST_SITE, "page"))
                check("the engine is running once more", engine_running(b))
                b.get(url(TEST_SITE, "onetrust"))
                check(
                    "on a site with blocking on, the banner is answered",
                    answered(b, "reject"),
                )
                b.get(url(OTHER_SITE, "onetrust"))
                check(
                    "on a site with blocking off, the banner is left alone",
                    untouched(b, "#onetrust-banner-sdk", timeout_ms=3000),
                )
    finally:
        pages.close()
    return check.result(
        "cookie banners are blocked and answered only when the switch is on"
    )


if __name__ == "__main__":
    sys.exit(main())
