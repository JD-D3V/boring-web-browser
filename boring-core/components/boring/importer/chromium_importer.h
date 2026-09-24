// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_IMPORTER_CHROMIUM_IMPORTER_H_
#define COMPONENTS_BORING_IMPORTER_CHROMIUM_IMPORTER_H_

#include <stdint.h>

#include <string>

#include "base/files/file_path.h"
#include "base/files/scoped_temp_dir.h"
#include "chrome/utility/importer/importer.h"

// Imports bookmarks, history and search engines from one Google Chrome
// or Microsoft Edge profile folder, found by chromium_profiles.cc.
//
// This file is built into //chrome/utility, next to Chromium's own
// importers, because it is one of them: it runs in the profile import
// utility process and hands what it reads to the ImporterBridge. It
// only ever reads copies, never the source browser's own files.
class ChromiumImporter : public Importer {
 public:
  ChromiumImporter();

  ChromiumImporter(const ChromiumImporter&) = delete;
  ChromiumImporter& operator=(const ChromiumImporter&) = delete;

  // Importer:
  void StartImport(const user_data_importer::SourceProfile& source_profile,
                   uint16_t items,
                   ImporterBridge* bridge) override;

 private:
  ~ChromiumImporter() override;

  void ImportBookmarks();
  void ImportHistory();
  void ImportSearchEngines();

  // Copies one database out of the profile folder, with its journal if
  // it has one, and returns the copy. Empty when there is nothing to
  // copy or the copy failed.
  base::FilePath CopyDatabase(const base::FilePath::StringType& name);

  base::FilePath source_path_;
  std::u16string importer_name_;
  base::ScopedTempDir copies_;
};

#endif  // COMPONENTS_BORING_IMPORTER_CHROMIUM_IMPORTER_H_
