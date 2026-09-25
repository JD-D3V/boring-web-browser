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
#include "url/gurl.h"

namespace boring {

namespace {

constexpr char kDisableSwitch[] = "disable-boring-adblock";

// How often the files are looked at again. Long enough to cost nothing
// per request, short enough that refreshed lists are picked up without
// restarting the browser.
constexpr base::TimeDelta kCheckInterval = base::Minutes(30);

const char kProfileListsKey[] = "boring_adblock_profile_lists";

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
  if (const PrefService* prefs = user_prefs::UserPrefs::Get(context)) {
    lists.cookie_notices = prefs->GetBoolean(prefs::kBoringHideCookieNotices);
    for (const base::Value& id : prefs->GetList(prefs::kBoringRegionalLists)) {
      if (id.is_string()) {
        lists.regional.push_back(id.GetString());
      }
    }
  }
  AdblockService::GetInstance()->WantLists(lists);
  holder->lists->Set(std::move(lists));
  return holder->lists;
}

ProfileLists::ProfileLists() = default;
ProfileLists::~ProfileLists() = default;

EnabledLists ProfileLists::Get() const {
  base::AutoLock lock(lock_);
  return lists_;
}

void ProfileLists::Set(EnabledLists lists) {
  base::AutoLock lock(lock_);
  lists_ = std::move(lists);
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
  std::set<std::string> regional_wanted;
  {
    base::AutoLock lock(lock_);
    cookies_wanted = cookies_wanted_;
    regional_wanted = regional_wanted_;
  }
  if (cookies_wanted) {
    LoadCookies();
  }
  for (const std::string& id : regional_wanted) {
    LoadRegional(id);
  }
}

void AdblockService::LoadResources() {
  const base::FilePath path = GetListPath(ListKind::kResources);
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
  }
  for (const auto& engine : engines) {
    lib->adblock_use_resources(engine->handle(), resources_);
  }
}

scoped_refptr<AdblockEngine> AdblockService::Build(
    const std::vector<std::pair<base::FilePath, bool>>& lists,
    Sources* sources) {
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
  std::vector<BoringAdblockList> entries(texts.size());
  for (size_t i = 0; i < texts.size(); ++i) {
    entries[i].text = reinterpret_cast<const unsigned char*>(texts[i].data());
    entries[i].len = texts[i].size();
    entries[i].trusted = trusted[i] ? 1 : 0;
  }
  void* handle = lib->adblock_new_lists(entries.data(), entries.size());
  if (!handle) {
    return nullptr;
  }
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
  scoped_refptr<AdblockEngine> built = Build(lists, &read);
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
  scoped_refptr<AdblockEngine> built = Build({{path, false}}, &read);
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
  scoped_refptr<AdblockEngine> built = Build({{path, false}}, &read);
  if (!built) {
    LOG(WARNING) << "boring adblock: regional list " << id << " did not build";
    return;
  }
  base::AutoLock lock(lock_);
  regional_[id] = std::move(built);
  regional_sources_[id] = std::move(read);
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
