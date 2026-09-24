// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_CORE_BORING_RELEASE_H_
#define COMPONENTS_BORING_CORE_BORING_RELEASE_H_

namespace boring {

// Our own release number on top of the Chromium version. The updater
// compares Chromium's version with this appended, 153.0.8010.52.1, so a
// release that fixes only our code, on the same Chromium, is still
// newer than the one before it.
//
// Add one for every published release. Set it back to 1 when the
// Chromium version moves, since the Chromium part already counts up.
// tools/make_appcast.py reads this line, so keep it on one line.
inline constexpr int kBoringRelease = 1;

}  // namespace boring

#endif  // COMPONENTS_BORING_CORE_BORING_RELEASE_H_
