// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_COLOR_BORING_COLOR_MIXER_H_
#define CHROME_BROWSER_UI_COLOR_BORING_COLOR_MIXER_H_

#include "ui/color/color_provider.h"
#include "ui/color/color_provider_key.h"

// Paints the window, tabs, toolbar and address bar in our own colours
// instead of the ones Chromium works out from a seed colour. Runs last,
// and only while the browser is on its default theme.
void AddBoringColorMixer(ui::ColorProvider* provider,
                         const ui::ColorProviderKey& key);

#endif  // CHROME_BROWSER_UI_COLOR_BORING_COLOR_MIXER_H_
