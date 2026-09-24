// Copyright 2026 boring. BSD style license.

#include "components/boring/importer/chromium_importer.h"

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "base/files/file.h"
#include "base/files/file_util.h"
#include "base/json/json_reader.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/utf_string_conversions.h"
#include "base/time/time.h"
#include "base/values.h"
#include "chrome/common/importer/importer_bridge.h"
#include "components/boring/importer/chromium_profiles.h"
#include "components/user_data_importer/common/imported_bookmark_entry.h"
#include "components/user_data_importer/common/importer_data_types.h"
#include "components/user_data_importer/common/importer_url_row.h"
#include "sql/database.h"
#include "sql/statement.h"
#include "url/gurl.h"

namespace {

// Database tags must be on sql's list at compile time, and this is the
// importer one. It only names the database in metrics, which this
// browser does not send.
inline constexpr sql::Database::Tag kDatabaseTag{"FirefoxImporter"};

// A Bookmarks file of this size is already absurd.
constexpr size_t kMaxBookmarksFileSize = 256 * 1024 * 1024;

// Chrome and Edge keep times as microseconds since 1601.
base::Time FromChromiumTime(int64_t microseconds) {
  return base::Time::FromDeltaSinceWindowsEpoch(
      base::Microseconds(microseconds));
}

bool CanImportBookmark(const GURL& url) {
  if (!url.is_valid()) {
    return false;
  }
  // Pages of the other browser itself (edge://, chrome-extension://)
  // mean nothing here, so only the ordinary kinds come across.
  return url.SchemeIsHTTPOrHTTPS() || url.SchemeIs("ftp") ||
         url.SchemeIsFile() || url.SchemeIs("javascript");
}

bool CanImportHistory(const GURL& url) {
  return url.is_valid() && url.SchemeIsHTTPOrHTTPS();
}

// Walks one bookmark folder. |path| holds the names of the folders
// above |node|, as ImportedBookmarkEntry wants them.
void ReadBookmarkNode(
    const base::DictValue& node,
    bool in_toolbar,
    std::vector<std::u16string>* path,
    std::vector<user_data_importer::ImportedBookmarkEntry>* out) {
  const std::string* type = node.FindString("type");
  const std::string* name = node.FindString("name");
  const std::u16string title = name ? base::UTF8ToUTF16(*name) : u"";

  base::Time created;
  if (const std::string* added = node.FindString("date_added")) {
    int64_t microseconds = 0;
    if (base::StringToInt64(*added, &microseconds)) {
      created = FromChromiumTime(microseconds);
    }
  }

  if (type && *type == "url") {
    const std::string* spec = node.FindString("url");
    GURL url(spec ? *spec : std::string());
    if (!CanImportBookmark(url)) {
      return;
    }
    user_data_importer::ImportedBookmarkEntry entry;
    entry.in_toolbar = in_toolbar;
    entry.is_folder = false;
    entry.url = url;
    entry.path = *path;
    entry.title = title;
    entry.creation_time = created;
    out->push_back(entry);
    return;
  }

  const base::ListValue* children = node.FindList("children");
  if (!children || children->empty()) {
    // An empty folder has no bookmark to carry its path, so it is sent
    // on its own.
    user_data_importer::ImportedBookmarkEntry entry;
    entry.in_toolbar = in_toolbar;
    entry.is_folder = true;
    entry.path = *path;
    entry.title = title;
    entry.creation_time = created;
    out->push_back(entry);
    return;
  }
  path->push_back(title);
  for (const base::Value& child : *children) {
    if (child.is_dict()) {
      ReadBookmarkNode(child.GetDict(), in_toolbar, path, out);
    }
  }
  path->pop_back();
}

// Reads one Bookmarks file. The bar keeps its own name at the top of
// each path, which ProfileWriter drops when it can put the bookmarks
// straight onto an empty bar. The other roots ("Other bookmarks" and
// the phone ones) are left out of the path, so their contents land in
// the "Imported from" folder without an extra level.
void ReadBookmarksFile(
    const base::FilePath& file,
    std::vector<user_data_importer::ImportedBookmarkEntry>* out) {
  std::string json;
  if (!base::ReadFileToStringWithMaxSize(file, &json, kMaxBookmarksFileSize)) {
    return;
  }
  std::optional<base::DictValue> root =
      base::JSONReader::ReadDict(json, base::JSON_PARSE_RFC);
  const base::DictValue* roots = root ? root->FindDict("roots") : nullptr;
  if (!roots) {
    return;
  }
  for (const char* key : {"bookmark_bar", "other", "synced"}) {
    const base::DictValue* folder = roots->FindDict(key);
    const base::ListValue* children =
        folder ? folder->FindList("children") : nullptr;
    if (!children) {
      continue;
    }
    const bool bar = std::string_view(key) == "bookmark_bar";
    std::vector<std::u16string> path;
    if (bar) {
      const std::string* name = folder->FindString("name");
      path.push_back(name ? base::UTF8ToUTF16(*name) : u"Bookmarks bar");
    }
    for (const base::Value& child : *children) {
      if (child.is_dict()) {
        ReadBookmarkNode(child.GetDict(), bar, &path, out);
      }
    }
  }
}

// Copies |from| to |to| while the other browser may have it open. It
// opens its databases shared for reading and writing, which a plain
// read that shares both too can still get past.
bool CopyOpenFile(const base::FilePath& from, const base::FilePath& to) {
  base::File in(from, base::File::FLAG_OPEN | base::File::FLAG_READ |
                          base::File::FLAG_WIN_SHARE_DELETE);
  if (!in.IsValid()) {
    return false;
  }
  base::File out(to, base::File::FLAG_CREATE_ALWAYS | base::File::FLAG_WRITE);
  if (!out.IsValid()) {
    return false;
  }
  return base::CopyFileContents(in, out);
}

}  // namespace

ChromiumImporter::ChromiumImporter() = default;

ChromiumImporter::~ChromiumImporter() = default;

void ChromiumImporter::StartImport(
    const user_data_importer::SourceProfile& source_profile,
    uint16_t items,
    ImporterBridge* bridge) {
  bridge_ = bridge;
  source_path_ = source_profile.source_path;
  importer_name_ = source_profile.importer_name;

  bridge_->NotifyStarted();
  if (!copies_.CreateUniqueTempDir()) {
    bridge_->NotifyEnded();
    return;
  }

  // History first: a favicon or visit count is only kept for a page the
  // profile already knows.
  if ((items & user_data_importer::HISTORY) && !cancelled()) {
    bridge_->NotifyItemStarted(user_data_importer::HISTORY);
    ImportHistory();
    bridge_->NotifyItemEnded(user_data_importer::HISTORY);
  }
  if ((items & user_data_importer::FAVORITES) && !cancelled()) {
    bridge_->NotifyItemStarted(user_data_importer::FAVORITES);
    ImportBookmarks();
    bridge_->NotifyItemEnded(user_data_importer::FAVORITES);
  }
  if ((items & user_data_importer::SEARCH_ENGINES) && !cancelled()) {
    bridge_->NotifyItemStarted(user_data_importer::SEARCH_ENGINES);
    ImportSearchEngines();
    bridge_->NotifyItemEnded(user_data_importer::SEARCH_ENGINES);
  }
  bridge_->NotifyEnded();
}

void ChromiumImporter::ImportBookmarks() {
  std::vector<user_data_importer::ImportedBookmarkEntry> bookmarks;
  ReadBookmarksFile(source_path_.Append(boring::kChromiumBookmarksFile),
                    &bookmarks);
  ReadBookmarksFile(source_path_.Append(boring::kChromiumAccountBookmarksFile),
                    &bookmarks);
  if (bookmarks.empty() || cancelled()) {
    return;
  }
  bridge_->AddBookmarks(bookmarks, u"Imported from " + importer_name_);
}

void ChromiumImporter::ImportHistory() {
  const base::FilePath file = CopyDatabase(boring::kChromiumHistoryFile);
  if (file.empty()) {
    return;
  }
  sql::Database db(kDatabaseTag);
  if (!db.Open(file)) {
    return;
  }
  sql::Statement s(db.GetUniqueStatement(
      "SELECT url, title, visit_count, typed_count, last_visit_time, hidden "
      "FROM urls"));
  if (!s.is_valid()) {
    return;
  }
  std::vector<user_data_importer::ImporterURLRow> rows;
  while (s.Step() && !cancelled()) {
    GURL url(s.ColumnStringView(0));
    if (!CanImportHistory(url)) {
      continue;
    }
    user_data_importer::ImporterURLRow row(url);
    row.title = s.ColumnString16(1);
    row.visit_count = s.ColumnInt(2);
    row.typed_count = s.ColumnInt(3);
    row.last_visit = FromChromiumTime(s.ColumnInt64(4));
    row.hidden = s.ColumnInt(5) != 0;
    rows.push_back(row);
  }
  if (!rows.empty() && !cancelled()) {
    // These are pages the person really visited, in the other browser.
    bridge_->SetHistoryItems(rows, user_data_importer::VISIT_SOURCE_BROWSED);
  }
}

void ChromiumImporter::ImportSearchEngines() {
  const base::FilePath file = CopyDatabase(boring::kChromiumWebDataFile);
  if (file.empty()) {
    return;
  }
  sql::Database db(kDatabaseTag);
  if (!db.Open(file) || !db.DoesTableExist("keywords")) {
    return;
  }
  // Only the engines the person added. The built in ones (Google and
  // the rest of the prepopulated list) and the @tabs style shortcuts
  // are the other browser's defaults, not their choices, and whatever
  // a policy put there belongs to that browser's administrator.
  std::string query =
      "SELECT short_name, keyword, url FROM keywords WHERE prepopulate_id = 0";
  if (db.DoesColumnExist("keywords", "starter_pack_id")) {
    query += " AND starter_pack_id = 0";
  }
  if (db.DoesColumnExist("keywords", "created_by_policy")) {
    query += " AND created_by_policy = 0";
  }
  // 2 is "turned off" in TemplateURLData::ActiveStatus.
  if (db.DoesColumnExist("keywords", "is_active")) {
    query += " AND is_active != 2";
  }
  sql::Statement s(db.GetUniqueStatement(query));
  if (!s.is_valid()) {
    return;
  }
  std::vector<user_data_importer::SearchEngineInfo> engines;
  while (s.Step() && !cancelled()) {
    user_data_importer::SearchEngineInfo engine;
    engine.display_name = s.ColumnString16(0);
    engine.keyword = s.ColumnString16(1);
    engine.url = s.ColumnString16(2);
    // Google's own parameters only mean something to Google's engines,
    // which are not imported.
    if (engine.keyword.empty() || engine.url.empty() ||
        engine.url.find(u"{google:") != std::u16string::npos) {
      continue;
    }
    engines.push_back(engine);
  }
  if (!engines.empty() && !cancelled()) {
    // Skips any engine this browser already has for the same address.
    bridge_->SetKeywords(engines, /*unique_on_host_and_path=*/true);
  }
}

base::FilePath ChromiumImporter::CopyDatabase(
    const base::FilePath::StringType& name) {
  const base::FilePath from = source_path_.Append(name);
  if (!base::PathExists(from)) {
    return base::FilePath();
  }
  const base::FilePath to = copies_.GetPath().Append(name);
  if (!CopyOpenFile(from, to)) {
    return base::FilePath();
  }
  // A journal left behind holds changes the main file does not have
  // yet. SQLite finishes or rolls them back when it opens the copy, as
  // it would for the other browser, so the copy reads consistently.
  for (const base::FilePath::CharType* suffix :
       {FILE_PATH_LITERAL("-journal"), FILE_PATH_LITERAL("-wal")}) {
    const base::FilePath side = base::FilePath(from.value() + suffix);
    if (base::PathExists(side)) {
      CopyOpenFile(side, base::FilePath(to.value() + suffix));
    }
  }
  return to;
}
