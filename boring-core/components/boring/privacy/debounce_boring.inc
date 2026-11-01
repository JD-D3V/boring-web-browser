// Copyright 2026 boring. BSD style license.
//
// Debounce rules of our own, for redirectors that Brave's list leaves out
// on purpose (its wiki calls the ones from Facebook and Google
// out-of-scope, because those sites use them to check outbound links
// for malicious pages). We skip them anyway: the page the link leads to
// still goes through our own protections as an ordinary navigation, and
// a redirector is a tracking hop whichever way it is looked at.
//
// Also the AMP viewer address (/v/s/), which Brave's file has no rule for
// (it has the /c/s/ one).
//
// Same shape as Brave's file, read by the same code, one rule each:
//   include        match patterns, scheme://host/path with * wildcards
//                  (scheme * is http or https, host *.x.com is x.com and
//                  everything under it, any port); the path is matched
//                  against path plus query
//   exclude        the same, patterns that take a rule back out
//   action         "redirect": the target is the value of query
//                  parameter `param`, which has to appear exactly once
//   param          the query parameter that holds the target address
//   regex-path     instead of "redirect": param is a regex over path and
//                  query, its group is the target; prepend_scheme goes in
//                  front of a target that has no scheme
//
// Only addresses that are plainly http or https ever come out of a rule,
// see debounce.cc. Kept apart from debounce_brave.inc so that file stays
// Brave's, unchanged, under its own licence.
R"JSON([
  {
    "include": [
      "*://l.facebook.com/l.php?*",
      "*://lm.facebook.com/l.php?*",
      "*://l.messenger.com/l.php?*",
      "*://lm.messenger.com/l.php?*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "u"
  },
  {
    "include": [
      "*://*.cdn.ampproject.org/v/s/*"
    ],
    "exclude": [],
    "prepend_scheme": "https",
    "action": "regex-path",
    "param": "^/v/s/(.*)$"
  },
  {
    "include": [
      "*://l.instagram.com/?*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "u"
  },
  {
    "include": [
      "*://google.com/url?*",
      "*://www.google.com/url?*",
      "*://www.google.co.uk/url?*",
      "*://www.google.ca/url?*",
      "*://www.google.com.au/url?*",
      "*://www.google.de/url?*",
      "*://www.google.fr/url?*",
      "*://www.google.es/url?*",
      "*://www.google.it/url?*",
      "*://www.google.nl/url?*",
      "*://www.google.co.in/url?*",
      "*://www.google.com.br/url?*",
      "*://www.google.co.jp/url?*",
      "*://www.google.com.mx/url?*",
      "*://www.google.ru/url?*",
      "*://www.google.pl/url?*",
      "*://www.google.se/url?*",
      "*://www.google.ch/url?*",
      "*://www.google.at/url?*",
      "*://www.google.be/url?*",
      "*://www.google.ie/url?*",
      "*://www.google.co.nz/url?*",
      "*://www.google.co.za/url?*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "q"
  },
  {
    "include": [
      "*://google.com/url?*",
      "*://www.google.com/url?*",
      "*://www.google.co.uk/url?*",
      "*://www.google.ca/url?*",
      "*://www.google.com.au/url?*",
      "*://www.google.de/url?*",
      "*://www.google.fr/url?*",
      "*://www.google.es/url?*",
      "*://www.google.it/url?*",
      "*://www.google.nl/url?*",
      "*://www.google.co.in/url?*",
      "*://www.google.com.br/url?*",
      "*://www.google.co.jp/url?*",
      "*://www.google.com.mx/url?*",
      "*://www.google.ru/url?*",
      "*://www.google.pl/url?*",
      "*://www.google.se/url?*",
      "*://www.google.ch/url?*",
      "*://www.google.at/url?*",
      "*://www.google.be/url?*",
      "*://www.google.ie/url?*",
      "*://www.google.co.nz/url?*",
      "*://www.google.co.za/url?*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "url"
  },
  {
    "include": [
      "*://www.youtube.com/redirect?*",
      "*://youtube.com/redirect?*",
      "*://m.youtube.com/redirect?*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "q"
  },
  {
    "include": [
      "*://out.reddit.com/*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "url"
  },
  {
    "include": [
      "*://www.linkedin.com/safety/go/?*",
      "*://www.linkedin.com/safety/go?*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "url"
  },
  {
    "include": [
      "*://steamcommunity.com/linkfilter/?*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "u"
  },
  {
    "include": [
      "*://steamcommunity.com/linkfilter/?*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "url"
  },
  {
    "include": [
      "*://duckduckgo.com/l/?*",
      "*://www.duckduckgo.com/l/?*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "uddg"
  },
  {
    "include": [
      "*://slack-redir.net/link?*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "url"
  },
  {
    "include": [
      "*://vk.com/away.php?*"
    ],
    "exclude": [],
    "action": "redirect",
    "param": "to"
  }
])JSON"
