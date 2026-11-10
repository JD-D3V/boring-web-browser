// Copyright 2026 boring. BSD style license.

#include "components/boring/folder_copy/folder_copy.h"

#include <memory>
#include <set>
#include <tuple>
#include <utility>

#include "base/command_line.h"
#include "base/files/file_util.h"
#include "base/files/important_file_writer.h"
#include "base/functional/bind.h"
#include "base/memory/ptr_util.h"
#include "base/memory/ref_counted.h"
#include "base/strings/string_number_conversions.h"
#include "base/task/bind_post_task.h"
#include "base/task/thread_pool.h"
#include "chrome/browser/bookmarks/bookmark_html_writer.h"
#include "chrome/browser/bookmarks/bookmark_model_factory.h"
#include "chrome/browser/importer/external_process_importer_host.h"
#include "chrome/browser/importer/importer_progress_observer.h"
#include "chrome/browser/importer/profile_writer.h"
#include "chrome/browser/profiles/profile.h"
#include "components/bookmarks/browser/bookmark_model.h"
#include "components/boring/core/boring_prefs.h"
#include "components/prefs/pref_service.h"
#include "components/user_data_importer/common/imported_bookmark_entry.h"
#include "components/user_data_importer/common/importer_data_types.h"
#include "components/user_data_importer/common/importer_type.h"
#include "url/gurl.h"

namespace boring::folder_copy {

namespace {

constexpr char kUserDataKey[] = "boring-folder-copy";
constexpr char kExportTempName[] = "folder-copy-export.tmp";
constexpr base::TimeDelta kDebounce = base::Seconds(3);
constexpr base::TimeDelta kStartupDelay = base::Seconds(5);
constexpr size_t kMaxBookmarksFileBytes = 64 * 1024 * 1024;
const base::TaskTraits kBlocking = {
    base::MayBlock(), base::TaskPriority::USER_VISIBLE,
    base::TaskShutdownBehavior::SKIP_ON_SHUTDOWN};

bool FolderHasCopy(const base::FilePath& dir) {
  return base::PathExists(dir.AppendASCII(kBookmarksFileName)) ||
         base::PathExists(dir.AppendASCII(kSettingsFileName));
}

FolderFiles ReadFolder(const base::FilePath& dir) {
  FolderFiles files;
  files.dir_ok = base::DirectoryExists(dir);
  if (!files.dir_ok) {
    return files;
  }
  files.has_bookmarks = base::PathExists(dir.AppendASCII(kBookmarksFileName));
  const base::FilePath settings = dir.AppendASCII(kSettingsFileName);
  files.has_settings = base::PathExists(settings);
  if (files.has_settings) {
    files.settings_read = base::ReadFileToStringWithMaxSize(
        settings, &files.settings, kMaxSettingsFileBytes);
  }
  return files;
}

// Skips the write when the file already says the same, so a cloud app is
// not told about a change that is not one.
bool WriteSettingsFile(const base::FilePath& dir, const std::string& text) {
  if (!base::DirectoryExists(dir)) {
    return false;
  }
  const base::FilePath path = dir.AppendASCII(kSettingsFileName);
  std::string old;
  if (base::ReadFileToStringWithMaxSize(path, &old, kMaxSettingsFileBytes) &&
      old == text) {
    return true;
  }
  return base::ImportantFileWriter::WriteFileAtomically(path, text);
}

// The export is written beside the profile and then put into the folder in
// one step, so the cloud app never sees half a file.
bool CopyExport(const base::FilePath& temp, const base::FilePath& dir) {
  std::string data;
  bool ok = base::ReadFileToStringWithMaxSize(temp, &data,
                                              kMaxBookmarksFileBytes) &&
            base::ImportantFileWriter::WriteFileAtomically(
                dir.AppendASCII(kBookmarksFileName), data);
  std::ignore = base::DeleteFile(temp);
  return ok;
}

// Adds what is new and nothing else: only http and https addresses, and
// none already bookmarked. Never touches a bookmark that exists.
class AddOnlyWriter : public ProfileWriter {
 public:
  explicit AddOnlyWriter(Profile* profile)
      : ProfileWriter(profile), profile_(profile) {}

  int added() const { return added_; }

  void AddBookmarks(
      const std::vector<user_data_importer::ImportedBookmarkEntry>& bookmarks,
      const std::u16string& top_level_folder_name) override {
    bookmarks::BookmarkModel* model =
        BookmarkModelFactory::GetForBrowserContext(profile_);
    std::vector<user_data_importer::ImportedBookmarkEntry> keep;
    std::set<GURL> seen;
    for (const auto& entry : bookmarks) {
      if (entry.is_folder || !entry.url.is_valid() ||
          !entry.url.SchemeIsHTTPOrHTTPS() || !model ||
          !model->GetNodesByURL(entry.url).empty() ||
          !seen.insert(entry.url).second) {
        continue;
      }
      keep.push_back(entry);
    }
    added_ += static_cast<int>(keep.size());
    ProfileWriter::AddBookmarks(keep, top_level_folder_name);
  }

 private:
  ~AddOnlyWriter() override = default;

  raw_ptr<Profile> profile_;
  int added_ = 0;
};

// Runs one import of bookmarks.html through Chromium's own importer, which
// reads the file in a utility process, and deletes itself when done.
class BookmarkLoad : public importer::ImporterProgressObserver {
 public:
  BookmarkLoad(Profile* profile,
               const base::FilePath& file,
               base::OnceCallback<void(int)> done)
      : writer_(base::MakeRefCounted<AddOnlyWriter>(profile)),
        done_(std::move(done)) {
    user_data_importer::SourceProfile source;
    source.importer_type = user_data_importer::TYPE_BOOKMARKS_FILE;
    source.source_path = file;
    // Deletes itself after ImportEnded().
    auto* host = new ExternalProcessImporterHost();
    host->set_observer(this);
    host->set_headless();
    host->StartImportSettings(source, profile, user_data_importer::FAVORITES,
                              writer_.get());
  }

 private:
  ~BookmarkLoad() override = default;

  void ImportStarted() override {}
  void ImportItemStarted(user_data_importer::ImportItem item) override {}
  void ImportItemEnded(user_data_importer::ImportItem item) override {}
  void ImportEnded() override {
    const int added = writer_->added();
    auto done = std::move(done_);
    delete this;
    std::move(done).Run(added);
  }

  scoped_refptr<AddOnlyWriter> writer_;
  base::OnceCallback<void(int)> done_;
};

}  // namespace

// static
void FolderCopy::Start(Profile* profile) {
  if (!profile || profile->IsOffTheRecord() || !profile->GetPrefs() ||
      profile->GetUserData(kUserDataKey)) {
    return;
  }
  auto copy = base::WrapUnique(new FolderCopy(profile));
  FolderCopy* raw = copy.get();
  profile->SetUserData(kUserDataKey, std::move(copy));
  raw->Init();
}

// static
FolderCopy* FolderCopy::Get(Profile* profile) {
  return profile ? static_cast<FolderCopy*>(profile->GetUserData(kUserDataKey))
                 : nullptr;
}

FolderCopy::FolderCopy(Profile* profile)
    : profile_(profile), prefs_(profile->GetPrefs()) {}

FolderCopy::~FolderCopy() = default;

void FolderCopy::Init() {
  registrar_.Init(prefs_);
  for (const std::string& name : SettingNames()) {
    registrar_.Add(name, base::BindRepeating(&FolderCopy::OnSettingChanged,
                                             base::Unretained(this)));
  }
  if (bookmarks::BookmarkModel* model =
          BookmarkModelFactory::GetForBrowserContext(profile_)) {
    model_observation_.Observe(model);
  }
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
  if (command_line->HasSwitch(kFolderCopyDirSwitch)) {
    const base::FilePath dir =
        command_line->GetSwitchValuePath(kFolderCopyDirSwitch);
    if (!dir.empty() && dir != Dir()) {
      SetDir(dir);
    }
  }
  ScheduleWrite(kStartupDelay);
}

base::DictValue FolderCopy::UiState() const {
  const base::FilePath dir = Dir();
  base::DictValue state;
  state.Set("available", true);
  state.Set("dir", dir.AsUTF8Unsafe());
  state.Set("on", !dir.empty());
  state.Set("waiting", !dir.empty() && !Armed() && !checking_);
  state.Set("loading", loading_);
  state.Set("savedAt", saved_at_.is_null()
                           ? 0.0
                           : saved_at_.InMillisecondsFSinceUnixEpoch());
  state.Set("error", error_);
  state.Set("message", message_);
  base::ListValue changes;
  for (const SettingChange& change : changes_) {
    base::DictValue item;
    item.Set("label", change.label);
    item.Set("from", change.from);
    item.Set("to", change.to);
    item.Set("weakens", change.weakens);
    changes.Append(std::move(item));
  }
  state.Set("changes", std::move(changes));
  return state;
}

base::CallbackListSubscription FolderCopy::Subscribe(
    base::RepeatingClosure callback) {
  return changed_.Add(std::move(callback));
}

base::FilePath FolderCopy::Dir() const {
  return prefs_->GetFilePath(prefs::kBoringFolderCopyDir);
}

bool FolderCopy::Armed() const {
  return prefs_->GetBoolean(prefs::kBoringFolderCopyArmed);
}

void FolderCopy::Arm() {
  prefs_->SetBoolean(prefs::kBoringFolderCopyArmed, true);
  ScheduleWrite(kDebounce);
}

void FolderCopy::Notify() {
  changed_.Notify();
}

void FolderCopy::SetDir(const base::FilePath& dir) {
  write_timer_.Stop();
  write_again_ = false;
  saved_at_ = base::Time();
  error_.clear();
  message_.clear();
  changes_.clear();
  pending_ = base::DictValue();
  prefs_->SetFilePath(prefs::kBoringFolderCopyDir, dir);
  prefs_->SetBoolean(prefs::kBoringFolderCopyArmed, false);
  checking_ = !dir.empty();
  if (checking_) {
    // A folder that has a copy already waits for the person to say which
    // way it goes. One that has none starts at once.
    base::ThreadPool::PostTaskAndReplyWithResult(
        FROM_HERE, kBlocking, base::BindOnce(&FolderHasCopy, dir),
        base::BindOnce(&FolderCopy::OnChecked, weak_factory_.GetWeakPtr(),
                       dir));
  }
  Notify();
}

void FolderCopy::OnChecked(const base::FilePath& dir, bool has_copy) {
  if (dir != Dir()) {
    return;
  }
  checking_ = false;
  if (!has_copy) {
    Arm();
  }
  Notify();
}

void FolderCopy::SaveOver() {
  if (Dir().empty() || Armed()) {
    return;
  }
  changes_.clear();
  pending_ = base::DictValue();
  message_.clear();
  prefs_->SetBoolean(prefs::kBoringFolderCopyArmed, true);
  WriteNow();
  Notify();
}

void FolderCopy::OnSettingChanged() {
  ScheduleWrite(kDebounce);
}

void FolderCopy::BookmarkModelChanged() {
  ScheduleWrite(kDebounce);
}

void FolderCopy::BookmarkModelBeingDeleted() {
  model_observation_.Reset();
}

void FolderCopy::ScheduleWrite(base::TimeDelta delay) {
  if (Dir().empty() || !Armed()) {
    return;
  }
  write_timer_.Start(FROM_HERE, delay,
                     base::BindOnce(&FolderCopy::WriteNow,
                                    base::Unretained(this)));
}

void FolderCopy::WriteNow() {
  const base::FilePath dir = Dir();
  if (dir.empty() || !Armed()) {
    return;
  }
  if (writing_) {
    write_again_ = true;
    return;
  }
  writing_ = true;
  base::ThreadPool::PostTaskAndReplyWithResult(
      FROM_HERE, kBlocking,
      base::BindOnce(&WriteSettingsFile, dir, BuildSettingsFile(prefs_)),
      base::BindOnce(&FolderCopy::OnSettingsWritten,
                     weak_factory_.GetWeakPtr()));
}

void FolderCopy::OnSettingsWritten(bool ok) {
  bookmarks::BookmarkModel* model =
      BookmarkModelFactory::GetForBrowserContext(profile_);
  if (!ok || Dir().empty()) {
    FinishWrite(false);
  } else if (!model || !model->loaded()) {
    // The model loading writes the bookmarks (BookmarkModelChanged).
    FinishWrite(true);
  } else {
    bookmark_html_writer::WriteBookmarks(
        profile_, profile_->GetPath().AppendASCII(kExportTempName),
        base::BindPostTaskToCurrentDefault(base::BindOnce(
            &FolderCopy::OnExported, weak_factory_.GetWeakPtr()),
            FROM_HERE));
  }
}

void FolderCopy::OnExported(bookmark_html_writer::Result result) {
  const base::FilePath dir = Dir();
  if (result != bookmark_html_writer::Result::kSuccess || dir.empty()) {
    FinishWrite(false);
    return;
  }
  base::ThreadPool::PostTaskAndReplyWithResult(
      FROM_HERE, kBlocking,
      base::BindOnce(&CopyExport,
                     profile_->GetPath().AppendASCII(kExportTempName), dir),
      base::BindOnce(&FolderCopy::OnExportCopied,
                     weak_factory_.GetWeakPtr()));
}

void FolderCopy::OnExportCopied(bool ok) {
  FinishWrite(ok);
}

void FolderCopy::FinishWrite(bool ok) {
  writing_ = false;
  if (ok) {
    saved_at_ = base::Time::Now();
    error_.clear();
  } else {
    error_ = "Could not write to this folder.";
  }
  Notify();
  if (write_again_) {
    write_again_ = false;
    ScheduleWrite(kDebounce);
  }
}

void FolderCopy::Load() {
  const base::FilePath dir = Dir();
  if (dir.empty() || loading_) {
    return;
  }
  loading_ = true;
  loading_dir_ = dir;
  message_.clear();
  changes_.clear();
  pending_ = base::DictValue();
  Notify();
  base::ThreadPool::PostTaskAndReplyWithResult(
      FROM_HERE, kBlocking, base::BindOnce(&ReadFolder, dir),
      base::BindOnce(&FolderCopy::OnFolderRead, weak_factory_.GetWeakPtr(),
                     dir));
}

void FolderCopy::OnFolderRead(const base::FilePath& dir, FolderFiles files) {
  if (dir != Dir()) {
    loading_ = false;
    return;
  }
  if (!files.dir_ok) {
    loading_ = false;
    error_ = "This folder is not there any more.";
    Notify();
    return;
  }
  error_.clear();
  // Settings are only listed here. They change after the person agrees.
  settings_note_.clear();
  if (!files.has_settings) {
    settings_note_ = " No settings file in this folder.";
  } else {
    std::optional<base::DictValue> values;
    if (files.settings_read) {
      values = ParseSettingsFile(files.settings);
    }
    if (!values) {
      settings_note_ = " The settings file could not be read.";
    } else {
      changes_ = DiffSettings(prefs_, *values);
      if (changes_.empty()) {
        settings_note_ = " Settings already match.";
      } else {
        pending_ = std::move(*values);
      }
    }
  }
  if (!files.has_bookmarks) {
    OnBookmarksLoaded(false, 0);
    return;
  }
  // Deletes itself when the import ends.
  new BookmarkLoad(profile_, dir.AppendASCII(kBookmarksFileName),
                   base::BindOnce(&FolderCopy::OnBookmarksLoaded,
                                  weak_factory_.GetWeakPtr(), true));
}

void FolderCopy::OnBookmarksLoaded(bool had_file, int added) {
  loading_ = false;
  if (!had_file) {
    message_ = "No bookmarks.html in this folder.";
  } else if (added == 0) {
    message_ = "No new bookmarks.";
  } else {
    message_ = "Added " + base::NumberToString(added) +
               (added == 1 ? " bookmark." : " bookmarks.");
  }
  message_ += settings_note_;
  if (changes_.empty() && !Dir().empty()) {
    // Nothing waits on the person: this browser may write again.
    Arm();
  }
  Notify();
}

void FolderCopy::ApplyPending() {
  if (changes_.empty()) {
    return;
  }
  const int applied = ApplySettings(prefs_, pending_);
  changes_.clear();
  pending_ = base::DictValue();
  message_ = "Changed " + base::NumberToString(applied) +
             (applied == 1 ? " setting." : " settings.");
  if (!Dir().empty()) {
    Arm();
  }
  Notify();
}

void FolderCopy::DropPending() {
  if (changes_.empty()) {
    return;
  }
  changes_.clear();
  pending_ = base::DictValue();
  message_ = "Settings left as they are.";
  if (!Dir().empty()) {
    Arm();
  }
  Notify();
}

}  // namespace boring::folder_copy
