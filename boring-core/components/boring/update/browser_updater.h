// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_UPDATE_BROWSER_UPDATER_H_
#define COMPONENTS_BORING_UPDATE_BROWSER_UPDATER_H_

#include <string>

#include "base/functional/callback_forward.h"

namespace boring {

// Keeps an installed browser up to date, through WinSparkle
// (https://winsparkle.org). WinSparkle reads a fixed feed on our site,
// downloads the newer installer it names, refuses it unless it carries
// an EdDSA signature made by our key, and runs it. Chromium's own
// installer then replaces the program files; the profile is not touched.
//
// Separate from the blocking lists on purpose: different feed, different
// key, different schedule. A browser update is code, a list is data.
//
// Everything here runs on the UI thread.
class BrowserUpdater {
 public:
  // Why a copy of the browser cannot update itself, if it cannot.
  enum class State {
    kStarting,      // Still loading, ask again shortly.
    kReady,         // Updates work.
    kNoKey,         // This build trusts no update key, so it asks nothing.
    kNotInstalled,  // A portable copy, not one the installer put there.
    kNoLibrary,     // WinSparkle.dll is missing or not the one we expect.
    kDisabled,      // Turned off on the command line.
  };

  // Starts the updater once per browser process; later calls do nothing.
  // |request_exit| closes the browser when WinSparkle has started an
  // installer and wants the old version out of the way.
  static void StartOnce(base::RepeatingClosure request_exit);

  static State GetState();

  // Whether the daily check is on. Stored by WinSparkle, per Windows user.
  static bool IsAutomatic();
  static void SetAutomatic(bool automatic);

  // Look now, with WinSparkle's own progress window. Does nothing unless
  // the state is kReady.
  static void CheckNow();

  // The version WinSparkle compares against the feed: Chromium's version
  // plus our own release number, e.g. 153.0.8010.52.1.
  static std::string BuildVersion();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_UPDATE_BROWSER_UPDATER_H_
