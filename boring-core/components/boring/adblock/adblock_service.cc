// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/adblock_service.h"

#include <algorithm>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/command_line.h"
#include "base/files/file.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/logging.h"
#include "base/memory/ref_counted.h"
#include "base/no_destructor.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_util.h"
#include "base/supports_user_data.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "base/values.h"
#include "components/boring/adblock/adblock_ffi.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/lists/list_paths.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "crypto/sha2.h"
#include "url/gurl.h"

namespace boring {

namespace {

constexpr char kDisableSwitch[] = "disable-boring-adblock";

// How often the files are looked at again. Long enough to cost nothing
// per request, short enough that refreshed lists are picked up without
// restarting the browser.
constexpr base::TimeDelta kCheckInterval = base::Minutes(30);

const char kProfileListsKey[] = "boring_adblock_profile_lists";

// The Aggressive blocking level, prefs::kBoringBlockingLevel.
constexpr int kAggressiveLevel = 1;

// Engine cache. Bump the format when the file layout changes or when
// engines start being built differently from the same lists, so no
// cache written the old way is ever loaded.
constexpr int kEngineCacheFormat = 1;
constexpr char kEngineCacheMagic[] = "boring-engine-cache";
constexpr base::FilePath::CharType kEngineCacheDir[] =
    FILE_PATH_LITERAL("engine-cache");
// The main engine serializes to about 8.5 MB. This is what we refuse
// to read, not what we expect.
constexpr size_t kMaxEngineCacheBytes = 256 * 1024 * 1024;
// Test only: append "<cache name> cache" or "<cache name> text" to this
// file for every engine built from lists, so the smoke test can see
// which way it went.
constexpr char kCacheReportSwitch[] = "boring-adblock-cache-report";

// Keeps one ProfileLists per profile. Holds only the copy, for the same
// reason as BlockingOffSites: user data can outlive the PrefService.
struct ProfileListsHolder : public base::SupportsUserData::Data {
  scoped_refptr<ProfileLists> lists = base::MakeRefCounted<ProfileLists>();
};

// A regional list id becomes part of a file name, and it comes from a
// pref, so only plain ids are accepted.
bool IsPlainId(const std::string& id) {
  if (id.empty() || id.size() > 64) {
    return false;
  }
  return std::ranges::all_of(id, [](char c) {
    return base::IsAsciiLower(c) || base::IsAsciiDigit(c) || c == '-' ||
           c == '_';
  });
}

int64_t WrittenAtUs(const base::FilePath& path) {
  base::File::Info info;
  if (path.empty() || !base::GetFileInfo(path, &info)) {
    return 0;
  }
  return info.last_modified.ToDeltaSinceWindowsEpoch().InMicroseconds();
}

// Owns a string the engine returned.
struct EngineString {
  explicit EngineString(char* s) : value(s) {}
  ~EngineString() {
    if (value) {
      GetBoringLibrary()->adblock_string_free(value);
    }
  }
  EngineString(const EngineString&) = delete;
  EngineString& operator=(const EngineString&) = delete;

  char* value;
};

// Where the cache for one engine is kept: beside the downloaded lists,
// so it is per machine like they are, and a test's --boring-list-dir
// keeps its cache apart too.
base::FilePath EngineCachePath(std::string_view cache_name) {
  const base::FilePath dir = GetDownloadedListDir();
  if (dir.empty()) {
    return base::FilePath();
  }
  return dir.Append(kEngineCacheDir)
      .AppendASCII(base::StrCat({cache_name, ".dat"}));
}

// The first line a cache file must start with to be used for these
// lists. It is a hash of the format, the crate that wrote the file, and
// the trust and SHA-256 of every list in order. The rest of the file is
// checked by the engine's own checksum when it loads.
std::string EngineCacheHeader(const std::vector<std::string>& texts,
                              const std::vector<bool>& trusted) {
  std::string key = base::StrCat(
      {kEngineCacheMagic, " format=", base::NumberToString(kEngineCacheFormat),
       " adblock=", GetBoringLibrary()->adblock_crate_version(), "\n"});
  for (size_t i = 0; i < texts.size(); ++i) {
    base::StrAppend(
        &key,
        {trusted[i] ? "trusted " : "standard ",
         base::HexEncodeLower(crypto::SHA256HashString(texts[i])), "\n"});
  }
  return base::StrCat({kEngineCacheMagic, " ",
                       base::HexEncodeLower(crypto::SHA256HashString(key)),
                       "\n"});
}

// Loads the engine cached at `path`, or returns null when there is none
// for exactly these lists or it does not load, in which case the caller
// builds from the lists.
void* LoadCachedEngine(const base::FilePath& path, const std::string& header) {
  std::string data;
  if (path.empty() ||
      !base::ReadFileToStringWithMaxSize(path, &data, kMaxEngineCacheBytes) ||
      !data.starts_with(header)) {
    return nullptr;
  }
  return GetBoringLibrary()->adblock_deserialize(
      reinterpret_cast<const unsigned char*>(data.data()) + header.size(),
      data.size() - header.size());
}

// Writes `engine` to the cache at `path`. A failure only costs the next
// start some time, so it is not reported.
void SaveCachedEngine(const base::FilePath& path,
                      const std::string& header,
                      void* engine) {
  const BoringLibrary* lib = GetBoringLibrary();
  if (path.empty() || !base::CreateDirectory(path.DirName())) {
    return;
  }
  size_t len = 0;
  unsigned char* bytes = lib->adblock_serialize(engine, &len);
  if (!bytes) {
    return;
  }
  std::string data = header;
  data.append(reinterpret_cast<const char*>(bytes), len);
  lib->adblock_bytes_free(bytes, len);
  // Into place in one step, so a browser starting meanwhile never reads
  // half a file.
  const base::FilePath part = path.AddExtensionASCII(".part");
  if (!base::WriteFile(part, data) || !base::ReplaceFile(part, path, nullptr)) {
    base::DeleteFile(part);
  }
}

void ReportCacheUse(std::string_view cache_name, bool from_cache) {
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
  if (!command_line->HasSwitch(kCacheReportSwitch)) {
    return;
  }
  base::AppendToFile(
      command_line->GetSwitchValuePath(kCacheReportSwitch),
      base::StrCat({cache_name, from_cache ? " cache\n" : " text\n"}));
}

void AppendStrings(const base::DictValue& dict,
                   std::string_view key,
                   std::set<std::string>* out) {
  const base::ListValue* list = dict.FindList(key);
  if (!list) {
    return;
  }
  for (const base::Value& item : *list) {
    if (const std::string* s = item.GetIfString()) {
      out->insert(*s);
    }
  }
}

std::vector<const char*> CStrings(const std::vector<std::string>& strings) {
  std::vector<const char*> out;
  out.reserve(strings.size());
  for (const std::string& s : strings) {
    out.push_back(s.c_str());
  }
  return out;
}

}  // namespace

AdblockEngine::AdblockEngine(void* handle) : handle_(handle) {}

AdblockEngine::~AdblockEngine() {
  if (!handle_) {
    return;
  }
  if (const BoringLibrary* lib = GetBoringLibrary()) {
    lib->adblock_free(handle_);
  }
}

EnabledLists::EnabledLists() = default;
EnabledLists::EnabledLists(const EnabledLists&) = default;
EnabledLists& EnabledLists::operator=(const EnabledLists&) = default;
EnabledLists::~EnabledLists() = default;

// static
scoped_refptr<ProfileLists> ProfileLists::ForContext(
    content::BrowserContext* context) {
  auto* holder =
      static_cast<ProfileListsHolder*>(context->GetUserData(kProfileListsKey));
  if (!holder) {
    auto owned = std::make_unique<ProfileListsHolder>();
    holder = owned.get();
    context->SetUserData(kProfileListsKey, std::move(owned));
  }
  EnabledLists lists;
  const PrefService* prefs = user_prefs::UserPrefs::Get(context);
  if (prefs) {
    lists.cookie_notices = prefs->GetBoolean(prefs::kBoringHideCookieNotices);
    for (const base::Value& id : prefs->GetList(prefs::kBoringRegionalLists)) {
      if (id.is_string()) {
        lists.regional.push_back(id.GetString());
      }
    }
    lists.aggressive =
        prefs->GetInteger(prefs::kBoringBlockingLevel) == kAggressiveLevel;
  }
  AdblockService* service = AdblockService::GetInstance();
  service->WantLists(lists);
  holder->lists->Set(std::move(lists));
  // Read on every navigation like the rest, so an edit on the Protection
  // page or a rule added by the element picker applies from the next
  // page load without anyone having to say so.
  if (prefs) {
    const std::string& custom = prefs->GetString(prefs::kBoringCustomRules);
    if (holder->lists->NoteCustomRules(custom)) {
      service->BuildCustomRules(holder->lists, custom);
    }
  }
  return holder->lists;
}

ProfileLists::ProfileLists() = default;
ProfileLists::~ProfileLists() = default;

EnabledLists ProfileLists::Get() const {
  base::AutoLock lock(lock_);
  EnabledLists lists = lists_;
  lists.custom = custom_;
  return lists;
}

void ProfileLists::Set(EnabledLists lists) {
  base::AutoLock lock(lock_);
  lists_ = std::move(lists);
}

bool ProfileLists::NoteCustomRules(const std::string& text) {
  base::AutoLock lock(lock_);
  if (custom_noted_ && text == custom_text_) {
    return false;
  }
  custom_noted_ = true;
  custom_text_ = text;
  return true;
}

void ProfileLists::SetCustomEngine(const std::string& text,
                                   scoped_refptr<AdblockEngine> engine) {
  base::AutoLock lock(lock_);
  // Built from rules that have changed since: a newer build is coming.
  if (text != custom_text_) {
    return;
  }
  custom_ = std::move(engine);
}

AdblockService::Decision::Decision() = default;
AdblockService::Decision::Decision(const Decision&) = default;
AdblockService::Decision& AdblockService::Decision::operator=(const Decision&) =
    default;
AdblockService::Decision::~Decision() = default;

// static
AdblockService* AdblockService::GetInstance() {
  static base::NoDestructor<AdblockService> instance;
  return instance.get();
}

AdblockService::AdblockService()
    : load_runner_(base::ThreadPool::CreateSequencedTaskRunner(
          {base::MayBlock(), base::TaskPriority::USER_VISIBLE})) {}

AdblockService::~AdblockService() = default;

// static
bool AdblockService::IsDisabled() {
  return base::CommandLine::ForCurrentProcess()->HasSwitch(kDisableSwitch);
}

void AdblockService::PostLoad() {
  load_runner_->PostTask(FROM_HERE,
                         base::BindOnce(&AdblockService::LoadOnBackgroundThread,
                                        base::Unretained(this)));
}

void AdblockService::EnsureLoading() {
  const int64_t now_us =
      base::Time::Now().ToDeltaSinceWindowsEpoch().InMicroseconds();

  if (!load_started_.exchange(true)) {
    last_checked_us_.store(now_us, std::memory_order_relaxed);
    PostLoad();
    return;
  }

  // Already loaded once. Look for newer lists now and then, rate
  // limited so this never touches the disk on a per request path.
  int64_t last = last_checked_us_.load(std::memory_order_relaxed);
  if (now_us - last < kCheckInterval.InMicroseconds()) {
    return;
  }
  if (!last_checked_us_.compare_exchange_strong(last, now_us,
                                                std::memory_order_relaxed)) {
    return;  // Another thread is already doing the check.
  }
  PostLoad();
}

void AdblockService::LoadOnBackgroundThread() {
  if (!GetBoringLibrary()) {
    LOG(ERROR) << "boring adblock: the engine did not load, ad and tracker "
                  "blocking is OFF";
    base::AutoLock lock(lock_);
    status_ = Status::kFailed;
    status_message_ = "the engine did not load";
    return;
  }

  // Resources first, so engines built below get the current ones.
  LoadResources();
  LoadMain();

  bool cookies_wanted;
  bool aggressive_wanted;
  std::set<std::string> regional_wanted;
  {
    base::AutoLock lock(lock_);
    cookies_wanted = cookies_wanted_;
    aggressive_wanted = aggressive_wanted_;
    regional_wanted = regional_wanted_;
  }
  if (cookies_wanted) {
    LoadCookies();
  }
  for (const std::string& id : regional_wanted) {
    LoadRegional(id);
  }
  if (aggressive_wanted) {
    LoadAggressive();
  }
}

void AdblockService::LoadResources() {
  // Only ever the copy that shipped with the browser. Scriptlets are
  // code that runs in pages, so they change with a signed browser
  // update and never with a list download, whatever the download
  // folder holds.
  const base::FilePath path = GetShippedListPath(ListKind::kResources);
  const int64_t mtime_us = WrittenAtUs(path);
  if (mtime_us == 0 || mtime_us == resources_mtime_us_) {
    return;  // Missing, or nothing has changed since we read it.
  }
  // Remember it even when it turns out broken, so a bad file is not
  // parsed again on every refresh.
  resources_mtime_us_ = mtime_us;

  const BoringLibrary* lib = GetBoringLibrary();
  std::string json;
  void* parsed = nullptr;
  if (base::ReadFileToString(path, &json) && !json.empty()) {
    parsed = lib->resources_new(
        reinterpret_cast<const unsigned char*>(json.data()), json.size());
  }
  if (!parsed) {
    // Blocking does not need them. Keep whatever was loaded before.
    LOG(WARNING) << "boring adblock: " << path << " could not be read, "
                 << "scriptlets and $redirect stay as they were";
    return;
  }
  VLOG(1) << "boring adblock: " << lib->resources_count(parsed)
          << " scriptlets and stubs";

  if (resources_) {
    lib->resources_free(resources_);
  }
  resources_ = parsed;

  // Engines already in use take the new ones too. Safe while they are
  // checking requests; the library locks each engine for the swap.
  std::vector<scoped_refptr<AdblockEngine>> engines;
  {
    base::AutoLock lock(lock_);
    if (main_) {
      engines.push_back(main_);
    }
    if (cookies_) {
      engines.push_back(cookies_);
    }
    for (const auto& [id, engine] : regional_) {
      engines.push_back(engine);
    }
    if (aggressive_) {
      engines.push_back(aggressive_);
    }
  }
  for (const auto& engine : engines) {
    lib->adblock_use_resources(engine->handle(), resources_);
  }
}

scoped_refptr<AdblockEngine> AdblockService::Build(
    const std::vector<std::pair<base::FilePath, bool>>& lists,
    Sources* sources,
    std::string_view cache_name) {
  const BoringLibrary* lib = GetBoringLibrary();
  sources->clear();
  // Read everything first: the entries below point into these strings.
  std::vector<std::string> texts;
  std::vector<bool> trusted;
  for (const auto& [path, is_trusted] : lists) {
    const int64_t mtime_us = WrittenAtUs(path);
    std::string text;
    if (mtime_us == 0 || !base::ReadFileToString(path, &text) || text.empty()) {
      continue;
    }
    (*sources)[path] = mtime_us;
    texts.push_back(std::move(text));
    trusted.push_back(is_trusted);
  }
  if (texts.empty()) {
    return nullptr;
  }
  const base::FilePath cache_path = EngineCachePath(cache_name);
  const std::string cache_header = EngineCacheHeader(texts, trusted);
  void* handle = LoadCachedEngine(cache_path, cache_header);
  const bool from_cache = handle != nullptr;
  if (!handle) {
    std::vector<BoringAdblockList> entries(texts.size());
    for (size_t i = 0; i < texts.size(); ++i) {
      entries[i].text = reinterpret_cast<const unsigned char*>(texts[i].data());
      entries[i].len = texts[i].size();
      entries[i].trusted = trusted[i] ? 1 : 0;
    }
    handle = lib->adblock_new_lists(entries.data(), entries.size());
    if (!handle) {
      return nullptr;
    }
    SaveCachedEngine(cache_path, cache_header, handle);
  }
  VLOG(1) << "boring adblock: " << cache_name << " engine "
          << (from_cache ? "loaded from its cache" : "built from the lists");
  ReportCacheUse(cache_name, from_cache);
  // Resources are never part of the cache, so a loaded engine gets them
  // the same way a built one does.
  if (resources_) {
    lib->adblock_use_resources(handle, resources_);
  }
  return base::MakeRefCounted<AdblockEngine>(handle);
}

void AdblockService::LoadMain() {
  // uBO's lists are trusted with every scriptlet, EasyList is not, so a
  // trusted scriptlet can only ever come from uBO's own rules.
  const std::vector<std::pair<base::FilePath, bool>> lists = {
      {GetListPath(ListKind::kFilters), false},
      {GetListPath(ListKind::kUbo), true},
  };
  Sources now;
  for (const auto& [path, trusted] : lists) {
    if (const int64_t mtime_us = WrittenAtUs(path)) {
      now[path] = mtime_us;
    }
  }

  auto fail = [this](const std::string& why) {
    base::AutoLock lock(lock_);
    // A failed refresh leaves the engine already in use alone. Only
    // report blocking as off when there is genuinely nothing loaded.
    if (!main_) {
      status_ = Status::kFailed;
      status_message_ = why;
    }
  };

  if (now.empty()) {
    LOG(ERROR) << "boring adblock: no filter list to load, ad and tracker "
                  "blocking is OFF";
    fail("the filter list file is missing");
    return;
  }
  {
    base::AutoLock lock(lock_);
    if (main_ && now == main_sources_) {
      return;  // Nothing has changed since we read them.
    }
  }

  Sources read;
  scoped_refptr<AdblockEngine> built = Build(lists, &read, "main");
  if (!built) {
    LOG(ERROR) << "boring adblock: engine failed to build, ad and tracker "
                  "blocking is OFF";
    fail("the filter lists could not be read");
    return;
  }
  int64_t newest_us = 0;
  for (const auto& [path, mtime_us] : read) {
    newest_us = std::max(newest_us, mtime_us);
  }
  {
    base::AutoLock lock(lock_);
    main_ = std::move(built);
    main_sources_ = std::move(read);
    loaded_mtime_us_ = newest_us;
    status_ = Status::kReady;
    status_message_.clear();
  }
  VLOG(1) << "boring adblock: main engine ready";
}

void AdblockService::LoadCookies() {
  const base::FilePath path = GetListPath(ListKind::kCookies);
  const int64_t mtime_us = WrittenAtUs(path);
  {
    base::AutoLock lock(lock_);
    if (mtime_us == 0 || (cookies_ && cookies_sources_[path] == mtime_us)) {
      return;
    }
  }
  Sources read;
  scoped_refptr<AdblockEngine> built =
      Build({{path, false}}, &read, "cookies");
  if (!built) {
    LOG(WARNING) << "boring adblock: cookie notice list did not build";
    return;
  }
  base::AutoLock lock(lock_);
  cookies_ = std::move(built);
  cookies_sources_ = std::move(read);
}

void AdblockService::LoadRegional(const std::string& id) {
  if (!IsPlainId(id)) {
    return;
  }
  const base::FilePath path = GetRegionalListPath(id);
  const int64_t mtime_us = WrittenAtUs(path);
  {
    base::AutoLock lock(lock_);
    if (mtime_us == 0 ||
        (regional_.contains(id) && regional_sources_[id][path] == mtime_us)) {
      return;
    }
  }
  Sources read;
  scoped_refptr<AdblockEngine> built =
      Build({{path, false}}, &read, base::StrCat({"regional-", id}));
  if (!built) {
    LOG(WARNING) << "boring adblock: regional list " << id << " did not build";
    return;
  }
  base::AutoLock lock(lock_);
  regional_[id] = std::move(built);
  regional_sources_[id] = std::move(read);
}

void AdblockService::LoadAggressive() {
  // uBO's annoyance filters are trusted like the rest of uBO's lists;
  // Fanboy's are not.
  const std::vector<std::pair<base::FilePath, bool>> lists = {
      {GetListPath(ListKind::kAggressiveUbo), true},
      {GetListPath(ListKind::kAggressiveFanboy), false},
  };
  Sources now;
  for (const auto& [path, trusted] : lists) {
    if (const int64_t mtime_us = WrittenAtUs(path)) {
      now[path] = mtime_us;
    }
  }
  {
    base::AutoLock lock(lock_);
    if (now.empty() || (aggressive_ && now == aggressive_sources_)) {
      return;
    }
  }
  Sources read;
  scoped_refptr<AdblockEngine> built = Build(lists, &read, "aggressive");
  if (!built) {
    LOG(WARNING) << "boring adblock: the Aggressive lists did not build";
    return;
  }
  base::AutoLock lock(lock_);
  aggressive_ = std::move(built);
  aggressive_sources_ = std::move(read);
}

void AdblockService::BuildCustomRules(scoped_refptr<ProfileLists> lists,
                                      std::string text) {
  if (IsDisabled()) {
    return;
  }
  load_runner_->PostTask(
      FROM_HERE, base::BindOnce(&AdblockService::BuildCustomOnBackgroundThread,
                                base::Unretained(this), std::move(lists),
                                std::move(text)));
}

void AdblockService::BuildCustomOnBackgroundThread(
    scoped_refptr<ProfileLists> lists,
    std::string text) {
  const BoringLibrary* lib = GetBoringLibrary();
  scoped_refptr<AdblockEngine> engine;
  if (lib && !base::TrimWhitespaceASCII(text, base::TRIM_ALL).empty()) {
    // For ##+js rules. Loaded here too in case this runs before the
    // first load has.
    LoadResources();
    // Standard permissions, never trusted: a rule copied from a web page
    // must not be able to run a trusted scriptlet.
    BoringAdblockList entry;
    entry.text = reinterpret_cast<const unsigned char*>(text.data());
    entry.len = text.size();
    entry.trusted = 0;
    if (void* handle = lib->adblock_new_lists(&entry, 1)) {
      if (resources_) {
        lib->adblock_use_resources(handle, resources_);
      }
      engine = base::MakeRefCounted<AdblockEngine>(handle);
    }
  }
  lists->SetCustomEngine(text, std::move(engine));
}

void AdblockService::WantLists(const EnabledLists& lists) {
  if (IsDisabled()) {
    return;
  }
  bool need_load = false;
  {
    base::AutoLock lock(lock_);
    if (lists.cookie_notices && !cookies_ && !cookies_wanted_) {
      cookies_wanted_ = true;
      need_load = true;
    }
    if (lists.aggressive && !aggressive_ && !aggressive_wanted_) {
      aggressive_wanted_ = true;
      need_load = true;
    }
    for (const std::string& id : lists.regional) {
      if (!regional_.contains(id) && IsPlainId(id) &&
          regional_wanted_.insert(id).second) {
        need_load = true;
      }
    }
  }
  if (!need_load) {
    return;
  }
  // The first load builds the main engine and then every engine wanted
  // by then. Once it has started, a later wish needs a load of its own.
  if (!load_started_.exchange(true)) {
    last_checked_us_.store(
        base::Time::Now().ToDeltaSinceWindowsEpoch().InMicroseconds(),
        std::memory_order_relaxed);
  }
  PostLoad();
}

std::vector<scoped_refptr<AdblockEngine>> AdblockService::EnginesFor(
    const EnabledLists& lists) {
  std::vector<scoped_refptr<AdblockEngine>> engines;
  bool need_load = false;
  {
    base::AutoLock lock(lock_);
    if (!main_) {
      return engines;
    }
    engines.push_back(main_);
    if (lists.cookie_notices) {
      if (cookies_) {
        engines.push_back(cookies_);
      } else if (!cookies_wanted_) {
        cookies_wanted_ = true;
        need_load = true;
      }
    }
    for (const std::string& id : lists.regional) {
      auto it = regional_.find(id);
      if (it != regional_.end()) {
        engines.push_back(it->second);
      } else if (IsPlainId(id) && regional_wanted_.insert(id).second) {
        need_load = true;
      }
    }
    if (lists.aggressive) {
      if (aggressive_) {
        engines.push_back(aggressive_);
      } else if (!aggressive_wanted_) {
        aggressive_wanted_ = true;
        need_load = true;
      }
    }
  }
  // The person's own rules go last, like uBO's "My filters": their
  // exceptions answer every list's blocks.
  if (lists.custom) {
    engines.push_back(lists.custom);
  }
  // Until an optional engine is built, its lists are simply not used.
  if (need_load) {
    PostLoad();
  }
  return engines;
}

bool AdblockService::IsReady() const {
  return status() == Status::kReady;
}

AdblockService::Status AdblockService::status() const {
  base::AutoLock lock(lock_);
  return status_;
}

std::string AdblockService::status_message() const {
  base::AutoLock lock(lock_);
  return status_message_;
}

base::Time AdblockService::list_time() const {
  base::AutoLock lock(lock_);
  if (loaded_mtime_us_ == 0) {
    return base::Time();
  }
  return base::Time::FromDeltaSinceWindowsEpoch(
      base::Microseconds(loaded_mtime_us_));
}

AdblockService::Decision AdblockService::Check(const GURL& url,
                                               const GURL& initiator,
                                               const std::string& request_type,
                                               const EnabledLists& lists) {
  Decision decision;
  if (!url.SchemeIsHTTPOrHTTPS() && !url.SchemeIsWSOrWSS()) {
    return decision;
  }
  const BoringLibrary* lib = GetBoringLibrary();
  if (!lib) {
    return decision;
  }
  const std::vector<scoped_refptr<AdblockEngine>> engines = EnginesFor(lists);
  if (engines.empty()) {
    return decision;
  }

  const std::string spec = url.spec();
  const std::string source = initiator.is_valid() ? initiator.spec() : "";
  // With more than one engine, every engine reports its exceptions even
  // when it has no block of its own, because a later engine's block has
  // to answer to them.
  const int force_exceptions = engines.size() > 1 ? 1 : 0;
  bool matched = false;
  bool exception = false;
  bool important = false;
  std::string redirect;
  for (const auto& engine : engines) {
    char* engine_redirect = nullptr;
    const int flags = lib->adblock_check_request(
        engine->handle(), spec.c_str(), source.c_str(), request_type.c_str(),
        matched ? 1 : 0, force_exceptions, &engine_redirect);
    EngineString owned(engine_redirect);
    if (owned.value && redirect.empty()) {
      redirect = owned.value;
    }
    matched |= (flags & kAdblockMatched) != 0;
    exception |= (flags & kAdblockException) != 0;
    if (flags & kAdblockImportant) {
      important = true;
      break;
    }
  }
  decision.block = important || (matched && !exception);
  // A $redirect-rule stub only applies to a request something blocks.
  if (decision.block) {
    decision.redirect = std::move(redirect);
  }
  return decision;
}

bool AdblockService::ShouldBlock(const GURL& url,
                                 const GURL& initiator,
                                 const std::string& request_type) {
  return Check(url, initiator, request_type, EnabledLists()).block;
}

mojom::UrlCosmeticResourcesPtr AdblockService::GetCosmeticResources(
    const GURL& url,
    const EnabledLists& lists) {
  if (!url.SchemeIsHTTPOrHTTPS()) {
    return nullptr;
  }
  const BoringLibrary* lib = GetBoringLibrary();
  if (!lib) {
    return nullptr;
  }
  const std::vector<scoped_refptr<AdblockEngine>> engines = EnginesFor(lists);
  if (engines.empty()) {
    return nullptr;
  }

  // Sets, because the same rule is often in more than one list.
  std::set<std::string> hide_selectors;
  std::set<std::string> procedural_actions;
  std::set<std::string> exceptions;
  auto result = mojom::UrlCosmeticResources::New();
  const std::string spec = url.spec();
  for (const auto& engine : engines) {
    EngineString json(
        lib->adblock_url_cosmetic_resources(engine->handle(), spec.c_str()));
    if (!json.value) {
      continue;
    }
    std::optional<base::DictValue> dict =
        base::JSONReader::ReadDict(json.value, base::JSON_PARSE_RFC);
    if (!dict) {
      continue;
    }
    AppendStrings(*dict, "hide_selectors", &hide_selectors);
    AppendStrings(*dict, "procedural_actions", &procedural_actions);
    AppendStrings(*dict, "exceptions", &exceptions);
    if (const std::string* script = dict->FindString("injected_script");
        script && !script->empty()) {
      result->injected_script += *script;
      result->injected_script += "\n";
    }
    // A $generichide exception in any list turns generic rules off for
    // the page, as it would in uBO.
    result->generichide |= dict->FindBool("generichide").value_or(false);
  }
  // Each engine already drops the selectors its own #@# rules except.
  // An exception in one list, most often a person's own rules, has to
  // answer the other lists' rules too.
  for (const std::string& exception : exceptions) {
    hide_selectors.erase(exception);
  }
  result->hide_selectors.assign(hide_selectors.begin(), hide_selectors.end());
  result->procedural_actions.assign(procedural_actions.begin(),
                                    procedural_actions.end());
  result->exceptions.assign(exceptions.begin(), exceptions.end());
  return result;
}

std::vector<std::string> AdblockService::GetHiddenClassIdSelectors(
    const std::vector<std::string>& classes,
    const std::vector<std::string>& ids,
    const std::vector<std::string>& exceptions,
    const EnabledLists& lists) {
  std::vector<std::string> selectors;
  const BoringLibrary* lib = GetBoringLibrary();
  if (!lib || (classes.empty() && ids.empty())) {
    return selectors;
  }
  const std::vector<scoped_refptr<AdblockEngine>> engines = EnginesFor(lists);
  if (engines.empty()) {
    return selectors;
  }

  const std::vector<const char*> class_ptrs = CStrings(classes);
  const std::vector<const char*> id_ptrs = CStrings(ids);
  const std::vector<const char*> exception_ptrs = CStrings(exceptions);
  std::set<std::string> merged;
  for (const auto& engine : engines) {
    EngineString json(lib->adblock_hidden_class_id_selectors(
        engine->handle(), class_ptrs.data(), class_ptrs.size(), id_ptrs.data(),
        id_ptrs.size(), exception_ptrs.data(), exception_ptrs.size()));
    if (!json.value) {
      continue;
    }
    std::optional<base::ListValue> list =
        base::JSONReader::ReadList(json.value, base::JSON_PARSE_RFC);
    if (!list) {
      continue;
    }
    for (const base::Value& item : *list) {
      if (const std::string* s = item.GetIfString()) {
        merged.insert(*s);
      }
    }
  }
  selectors.assign(merged.begin(), merged.end());
  return selectors;
}

// static
const char* AdblockService::RequestTypeFromDestination(
    network::mojom::RequestDestination destination,
    const GURL& url) {
  using network::mojom::RequestDestination;
  switch (destination) {
    case RequestDestination::kScript:
    case RequestDestination::kWorker:
    case RequestDestination::kSharedWorker:
    case RequestDestination::kServiceWorker:
      return "script";
    case RequestDestination::kImage:
      return "image";
    case RequestDestination::kStyle:
    case RequestDestination::kXslt:
      return "stylesheet";
    case RequestDestination::kDocument:
      return "document";
    case RequestDestination::kFrame:
    case RequestDestination::kIframe:
    case RequestDestination::kFencedframe:
    case RequestDestination::kEmbed:
    case RequestDestination::kObject:
      return "subdocument";
    case RequestDestination::kFont:
      return "font";
    case RequestDestination::kAudio:
    case RequestDestination::kVideo:
    case RequestDestination::kTrack:
      return "media";
    case RequestDestination::kReport:
      return "ping";
    case RequestDestination::kEmpty:
      if (url.SchemeIsWSOrWSS()) {
        return "websocket";
      }
      return "xmlhttprequest";
    case RequestDestination::kJson:
      return "xmlhttprequest";
    default:
      return "other";
  }
}

}  // namespace boring
