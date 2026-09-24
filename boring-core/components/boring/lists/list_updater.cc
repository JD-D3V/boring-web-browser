// Copyright 2026 boring. BSD style license.

#include "components/boring/lists/list_updater.h"

#include <algorithm>
#include <cstdint>
#include <string_view>
#include <utility>
#include <vector>

#include "base/base64.h"
#include "base/command_line.h"
#include "base/containers/span.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_split.h"
#include "base/strings/string_util.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "base/values.h"
#include "components/boring/core/boring_capabilities.h"
#include "components/boring/core/boring_prefs.h"
#include "components/prefs/pref_service.h"
#include "crypto/sha2.h"
#include "crypto/signature_verifier.h"
#include "net/base/load_flags.h"
#include "net/base/url_util.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/shared_url_loader_factory.h"
#include "services/network/public/cpp/simple_url_loader.h"
#include "url/url_constants.h"

namespace boring {

namespace {

// Where lists come from. One release tag that is replaced every week,
// so this address never has to change.
constexpr char kDefaultFeedUrl[] =
    "https://github.com/JD-D3V/boring-web-browser/releases/download/lists/";

constexpr char kManifestName[] = "lists.json";
constexpr char kManifestSignatureName[] = "lists.json.sig";

// The only signature algorithm we accept. Named in the signature file
// so a future one can be added without a browser mistaking the two.
constexpr char kSignatureAlgorithm[] = "ecdsa-p256-sha256";

// Read lists from somewhere else, which is how the smoke test drives
// this without touching the real host.
constexpr char kFeedUrlSwitch[] = "boring-list-url";
// Trust one more manifest signing key, given as the base64 of its
// SubjectPublicKeyInfo. Honoured only for a feed on this machine, the
// same rule the feed address itself follows, so nothing on the network
// can talk a browser into trusting a key of its choosing.
constexpr char kTestKeySwitch[] = "boring-list-key";
// Turn updates off for one run, without changing anyone's setting.
constexpr char kDisableSwitch[] = "disable-boring-list-updates";
// Look now, whatever the lists say about their own age. Only the
// smoke test uses this; nothing would ever finish testing if it
// had to wait a week for the real schedule to come round.
constexpr char kCheckNowSwitch[] = "boring-check-lists-now";

// A file whose timestamp is when we last looked and whose contents are
// what we saw. One plain file rather than a state format, so there is
// nothing that can drift out of step with the lists.
constexpr base::FilePath::CharType kMarkerFile[] =
    FILE_PATH_LITERAL("last-check");
constexpr std::string_view kMarkerVersionKey = "version";
constexpr std::string_view kMarkerDegradedKey = "degraded";
constexpr std::string_view kMarkerOutcomeKey = "outcome";

// How a check ended. One word each, written to the marker file so the
// browser can say what happened rather than guess from the lists'
// timestamps.
constexpr std::string_view kOutcomeOk = "ok";
constexpr std::string_view kOutcomeNetwork = "network";
constexpr std::string_view kOutcomeSignature = "signature";
constexpr std::string_view kOutcomeManifest = "manifest";
constexpr std::string_view kOutcomeContent = "content";
constexpr std::string_view kOutcomeStale = "stale";

// A key the browser will believe a manifest from, as the base64 of its
// SubjectPublicKeyInfo and the name it goes by. The name is the first
// 16 hex characters of the SHA-256 of that same DER, so a manifest can
// say which key signed it and a browser can say which key it trusted.
//
// There is room for more than one on purpose. A rotation ships as a
// build carrying both the old and the new key; once every published
// bundle is signed by the new one, a later build drops the old. A key
// that has to be revoked is removed the same way.
struct TrustedKey {
  std::string_view id;
  std::string_view spki_base64;
};

// TODO(JD): replace this placeholder with the real publishing key
// before the beta. Generate it off the network, keep the private half
// out of the repo, and paste the key id and base64 SPKI that
// publish_lists.py --gen-test-key prints for its own key here.
//
// Until that happens every manifest fails this check and no browser
// updates its lists. That is the safe direction to fail in: people
// keep the lists they already have. It is not the shipping state.
constexpr TrustedKey kTrustedKeys[] = {
    {"0000000000000000", "REPLACE-WITH-THE-REAL-PUBLISHING-KEY"},
};

// While the lists in use are younger than this, nothing is asked for at
// all, so a browser installed this week never says a word.
constexpr base::TimeDelta kFreshEnough = base::Days(7);

// Once they are old enough to be worth replacing, look this often.
constexpr base::TimeDelta kCheckInterval = base::Days(1);

// The manifest is a few hundred bytes, its signature under two, and
// the lists a few megabytes. These are what we refuse to read, not
// what we expect.
constexpr size_t kMaxManifestBytes = 64 * 1024;
constexpr size_t kMaxSignatureBytes = 8 * 1024;
constexpr size_t kMaxListBytes = 32 * 1024 * 1024;

std::string HashOfString(std::string_view data) {
  return base::HexEncodeLower(crypto::SHA256HashString(data));
}

std::string HashOfFile(const base::FilePath& path) {
  std::string data;
  if (path.empty() ||
      !base::ReadFileToStringWithMaxSize(path, &data, kMaxListBytes)) {
    return std::string();
  }
  return HashOfString(data);
}

base::FilePath MarkerPath() {
  const base::FilePath dir = GetDownloadedListDir();
  return dir.empty() ? base::FilePath() : dir.Append(kMarkerFile);
}

// What the marker file says, empty when there is none.
std::string ReadMarker() {
  std::string text;
  const base::FilePath path = MarkerPath();
  if (path.empty() || !base::ReadFileToStringWithMaxSize(path, &text, 1024)) {
    return std::string();
  }
  return text;
}

// One "key=value" line from the marker file, empty when it is absent.
// Whole lines, not a search through the text: searching would let one
// key's name be found inside another's.
std::string MarkerValue(std::string_view text, std::string_view key) {
  for (std::string_view line : base::SplitStringPiece(
           text, "\n", base::TRIM_WHITESPACE, base::SPLIT_WANT_NONEMPTY)) {
    if (line.size() > key.size() && line.starts_with(key) &&
        line[key.size()] == '=') {
      return std::string(line.substr(key.size() + 1));
    }
  }
  return std::string();
}

// The name a key goes by, so a manifest can say which one signed it.
std::string KeyIdFor(base::span<const uint8_t> spki) {
  return base::HexEncodeLower(crypto::SHA256Hash(spki)).substr(0, 16);
}

// The extra key a test may name on the command line, empty when there
// is none to honour.
std::vector<uint8_t> TestKey() {
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
  if (!command_line->HasSwitch(kTestKeySwitch)) {
    return {};
  }
  // Same rule as the feed address: anything but the built in default
  // is honoured only for a server on this machine. Without this, a
  // shortcut with an extra switch on it would be enough to make a
  // browser trust somebody else's lists.
  if (!net::IsLocalhost(ListUpdater::GetFeedUrl())) {
    return {};
  }
  const std::optional<std::vector<uint8_t>> spki =
      base::Base64Decode(command_line->GetSwitchValueASCII(kTestKeySwitch));
  return spki.value_or(std::vector<uint8_t>());
}

// The SubjectPublicKeyInfo of the key with this name, empty when we do
// not trust a key by that name.
std::vector<uint8_t> TrustedKeyNamed(std::string_view id) {
  for (const TrustedKey& key : kTrustedKeys) {
    if (key.id != id) {
      continue;
    }
    const std::optional<std::vector<uint8_t>> spki =
        base::Base64Decode(key.spki_base64);
    if (spki) {
      return *spki;
    }
  }
  const std::vector<uint8_t> test_key = TestKey();
  if (!test_key.empty() && KeyIdFor(test_key) == id) {
    return test_key;
  }
  return {};
}

// True when some manifest could pass the signature check at all. With
// only the placeholder built in, none can, so asking for one is a
// request that is certain to be thrown away.
bool HasUsableKey() {
  for (const TrustedKey& key : kTrustedKeys) {
    const std::optional<std::vector<uint8_t>> spki =
        base::Base64Decode(key.spki_base64);
    if (spki && !spki->empty() && KeyIdFor(*spki) == key.id) {
      return true;
    }
  }
  return !TestKey().empty();
}

// True when this manifest really was written by someone holding a key
// this browser was built to trust.
//
// The manifest's own bytes are what is signed, so they are checked
// before they are parsed. The signature file has to be read first to
// find out which key to look up, but nothing in it is believed: a name
// we do not know, or a signature that does not verify, both end here.
bool ManifestIsSigned(const std::string& manifest,
                      const std::string& signature_file) {
  const std::optional<base::DictValue> parsed =
      base::JSONReader::ReadDict(signature_file, base::JSON_PARSE_RFC);
  if (!parsed) {
    return false;
  }
  const std::string* algorithm = parsed->FindString("alg");
  const std::string* key_id = parsed->FindString("key");
  const std::string* signature_base64 = parsed->FindString("sig");
  if (!algorithm || !key_id || !signature_base64 ||
      *algorithm != kSignatureAlgorithm) {
    return false;
  }

  const std::vector<uint8_t> spki = TrustedKeyNamed(*key_id);
  if (spki.empty()) {
    return false;
  }
  const std::optional<std::vector<uint8_t>> signature =
      base::Base64Decode(*signature_base64);
  if (!signature) {
    return false;
  }

  // TODO(JD): crypto::SignatureVerifier is marked for removal upstream
  // in favour of crypto/sign. Move to it on a Chromium roll that still
  // has both, rather than on the one that drops this.
  crypto::SignatureVerifier verifier;
  if (!verifier.VerifyInit(crypto::SignatureVerifier::ECDSA_SHA256, *signature,
                           spki)) {
    return false;
  }
  verifier.VerifyUpdate(base::as_byte_span(manifest));
  return verifier.VerifyFinal();
}

std::unique_ptr<network::SimpleURLLoader> MakeLoader(const GURL& url,
                                                     bool no_cache) {
  net::NetworkTrafficAnnotationTag annotation =
      net::DefineNetworkTrafficAnnotation("boring_blocking_lists", R"(
        semantics {
          sender: "boring blocking lists"
          description:
            "Downloads the ad and tracker blocking lists the browser "
            "filters with, so that a browser installed months ago "
            "still recognises what is being served today."
          trigger:
            "Checked at most once a day, and only once the lists "
            "already in use are more than a week old. A list is "
            "downloaded only when its hash shows it changed."
          data:
            "Nothing about the user or the pages they visit. A plain "
            "request for a fixed file, with no cookies and no "
            "identifier of any kind."
          destination: OTHER
          destination_other: "The project's own release host."
        }
        policy {
          cookies_allowed: NO
          setting:
            "On by default. Turned off with Keep blocking lists up to "
            "date, on the Protection page."
          policy_exception_justification: "Not implemented yet."
        })");

  auto request = std::make_unique<network::ResourceRequest>();
  request->url = url;
  request->method = "GET";
  request->credentials_mode = network::mojom::CredentialsMode::kOmit;
  if (no_cache) {
    // A cached manifest would answer the one question this is asking.
    request->load_flags = net::LOAD_DISABLE_CACHE;
  }
  return network::SimpleURLLoader::Create(std::move(request), annotation);
}

}  // namespace

// static
ListUpdater* ListUpdater::GetInstance() {
  static base::NoDestructor<ListUpdater> instance;
  return instance.get();
}

ListUpdater::ListUpdater() = default;

ListUpdater::~ListUpdater() = default;

// static
GURL ListUpdater::GetFeedUrl() {
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
  GURL url(kDefaultFeedUrl);
  if (command_line->HasSwitch(kFeedUrlSwitch)) {
    url = GURL(command_line->GetSwitchValueASCII(kFeedUrlSwitch));
    // Plain http is allowed only for a server on this machine, which is
    // how the smoke test drives it. Anywhere else these files have to
    // arrive over something nobody on the path can rewrite.
    if (!url.is_valid() ||
        (!url.SchemeIs(url::kHttpsScheme) && !net::IsLocalhost(url))) {
      return GURL();
    }
  }
  // The feed names a folder, so make it read like one before anything
  // is resolved against it.
  std::string spec = url.spec();
  if (!spec.empty() && spec.back() != '/') {
    spec.push_back('/');
    url = GURL(spec);
  }
  return url;
}

// static
bool ListUpdater::CanUpdate() {
  return HasUsableKey();
}

// static
bool ListUpdater::IsEnabled(const PrefService* prefs) {
  if (!CanUpdate()) {
    return false;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(kDisableSwitch)) {
    return false;
  }
  // No prefs means nobody has said otherwise, so the default stands.
  return !prefs || prefs->GetBoolean(prefs::kListUpdates);
}

void ListUpdater::MaybeCheck(
    const PrefService* prefs,
    scoped_refptr<network::SharedURLLoaderFactory> factory) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (running_ || !factory || !IsEnabled(prefs) || !GetFeedUrl().is_valid()) {
    return;
  }
  running_ = true;
  asked_ = false;
  all_saved_ = true;
  degraded_ = false;
  outcome_.clear();
  factory_ = std::move(factory);
  base::ThreadPool::PostTaskAndReplyWithResult(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::BEST_EFFORT},
      base::BindOnce(&ListUpdater::LookAtWhatWeHave),
      base::BindOnce(&ListUpdater::OnLookedAtDisk, weak_factory_.GetWeakPtr()));
}

// static
ListUpdater::Local ListUpdater::LookAtWhatWeHave() {
  Local local;
  if (GetDownloadedListDir().empty()) {
    return local;  // Nowhere to put a list, so nothing worth asking for.
  }

  const base::Time now = base::Time::Now();
  const bool ignore_schedule =
      base::CommandLine::ForCurrentProcess()->HasSwitch(kCheckNowSwitch);

  // While the lists actually in use are still fresh there is nothing to
  // ask about. A missing list has no time at all, which counts as the
  // most urgent case rather than the freshest.
  const base::Time filters_at = GetWrittenAt(GetListPath(ListKind::kFilters));
  const base::Time scam_at = kScamBlockingAvailable
                                 ? GetWrittenAt(GetListPath(ListKind::kScam))
                                 : filters_at;
  if (!ignore_schedule && !filters_at.is_null() && !scam_at.is_null() &&
      now - std::min(filters_at, scam_at) < kFreshEnough) {
    return local;
  }

  // Past that, look no more than once a day.
  const base::Time checked = GetWrittenAt(MarkerPath());
  if (!ignore_schedule && !checked.is_null() &&
      now - checked < kCheckInterval) {
    return local;
  }

  local.worth_asking = true;
  const std::string marker = ReadMarker();
  base::StringToInt(MarkerValue(marker, kMarkerVersionKey), &local.version);
  local.degraded = MarkerValue(marker, kMarkerDegradedKey) == "1";
  local.filters_sha256 = HashOfFile(GetDownloadedListPath(ListKind::kFilters));
  if (kScamBlockingAvailable) {
    local.scam_sha256 = HashOfFile(GetDownloadedListPath(ListKind::kScam));
  }
  return local;
}

void ListUpdater::OnLookedAtDisk(Local local) {
  if (!local.worth_asking) {
    Finish();
    return;
  }
  local_ = std::move(local);
  // Until a manifest says otherwise, the version on record is the one
  // already on disk. Without this, giving up part way through would
  // write down version 0 and let a stale manifest back in next time.
  version_ = local_.version;
  asked_ = true;
  loader_ = MakeLoader(GetFeedUrl().Resolve(kManifestName), /*no_cache=*/true);
  loader_->DownloadToString(
      factory_.get(),
      base::BindOnce(&ListUpdater::OnManifest, weak_factory_.GetWeakPtr()),
      kMaxManifestBytes);
}

void ListUpdater::OnManifest(std::optional<std::string> body) {
  loader_.reset();
  if (!body) {
    FinishWith(kOutcomeNetwork);
    return;
  }
  // Hold the bytes exactly as served. They are what was signed, and
  // nothing in them is looked at until the signature says who wrote
  // them.
  manifest_ = std::move(*body);
  loader_ = MakeLoader(GetFeedUrl().Resolve(kManifestSignatureName),
                       /*no_cache=*/true);
  loader_->DownloadToString(factory_.get(),
                            base::BindOnce(&ListUpdater::OnManifestSignature,
                                           weak_factory_.GetWeakPtr()),
                            kMaxSignatureBytes);
}

void ListUpdater::OnManifestSignature(std::optional<std::string> body) {
  loader_.reset();
  // A missing signature and a wrong one are the same answer. Either
  // way this manifest is not one we can say came from us, so nothing
  // changes and the version on disk stays where it is. Treated exactly
  // like a download that did not arrive.
  if (!body || !ManifestIsSigned(manifest_, *body)) {
    FinishWith(kOutcomeSignature);
    return;
  }
  ApplyManifest();
}

void ListUpdater::ApplyManifest() {
  // Strict JSON: this file is one we generate ourselves, so there is no
  // reason to accept comments or trailing commas in it.
  const std::optional<base::DictValue> parsed =
      base::JSONReader::ReadDict(manifest_, base::JSON_PARSE_RFC);
  if (!parsed) {
    FinishWith(kOutcomeManifest);
    return;
  }
  const std::optional<int> version = parsed->FindInt("version");
  const base::ListValue* files = parsed->FindList("files");
  if (!version || !files) {
    FinishWith(kOutcomeManifest);
    return;
  }
  // The publisher only ever counts up, so a manifest older than the one
  // already applied is a stale copy and must not walk us backwards.
  if (*version < local_.version) {
    FinishWith(kOutcomeStale);
    return;
  }
  version_ = *version;
  // The publisher says so when it built a bundle without one of its
  // sources. Passed on as it stands, so nothing downstream has to
  // guess whether a thin list is thin on purpose.
  degraded_ = parsed->FindBool("degraded").value_or(false);

  wanted_.clear();
  next_ = 0;
  for (const base::Value& item : *files) {
    const base::DictValue* entry = item.GetIfDict();
    if (!entry) {
      continue;
    }
    const std::string* name = entry->FindString("name");
    const std::string* sha256 = entry->FindString("sha256");
    const std::optional<int> size = entry->FindInt("size");
    if (!name || !sha256 || !size || *size <= 0 ||
        static_cast<size_t>(*size) > kMaxListBytes) {
      continue;
    }
    const std::optional<ListKind> kind = ListKindFromName(*name);
    if (!kind) {
      continue;  // A list this version of the browser does not know.
    }
    if (*kind == ListKind::kScam && !kScamBlockingAvailable) {
      // This version ships no scam list and must not start using one
      // an update feed happens to offer.
      continue;
    }
    const std::string& have = *kind == ListKind::kFilters
                                  ? local_.filters_sha256
                                  : local_.scam_sha256;
    if (base::EqualsCaseInsensitiveASCII(have, *sha256)) {
      continue;  // Already holding exactly this one.
    }
    wanted_.push_back({*kind, base::ToLowerASCII(*sha256), *size});
  }
  FetchNextList();
}

void ListUpdater::FetchNextList() {
  if (next_ >= wanted_.size()) {
    // Everything the manifest offered is either already here or has
    // just been put in place, so this version is the one in use.
    FinishWith(kOutcomeOk);
    return;
  }
  const Wanted& wanted = wanted_[next_];
  loader_ = MakeLoader(GetFeedUrl().Resolve(ListFileName(wanted.kind)),
                       /*no_cache=*/false);
  loader_->DownloadToString(factory_.get(),
                            base::BindOnce(&ListUpdater::OnListDownloaded,
                                           weak_factory_.GetWeakPtr()),
                            kMaxListBytes);
}

void ListUpdater::OnListDownloaded(std::optional<std::string> body) {
  loader_.reset();
  if (!body) {
    FinishWith(kOutcomeNetwork);
    return;
  }
  const Wanted& wanted = wanted_[next_];
  base::ThreadPool::PostTaskAndReplyWithResult(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::BEST_EFFORT},
      base::BindOnce(&ListUpdater::SaveList, wanted.kind, wanted.sha256,
                     wanted.size, std::move(*body)),
      base::BindOnce(&ListUpdater::OnListSaved, weak_factory_.GetWeakPtr()));
}

// static
bool ListUpdater::SaveList(ListKind kind,
                           std::string sha256,
                           int64_t size,
                           std::string body) {
  // What arrived has to be exactly what the manifest promised. Anything
  // else is thrown away and the list in use is left as it is, because a
  // stale list still blocks and a mangled one blocks nothing.
  if (static_cast<int64_t>(body.size()) != size ||
      HashOfString(body) != sha256) {
    return false;
  }
  const base::FilePath dir = GetDownloadedListDir();
  if (dir.empty() || !base::CreateDirectory(dir)) {
    return false;
  }
  const base::FilePath path = dir.AppendASCII(ListFileName(kind));
  const base::FilePath part = path.AddExtensionASCII(".part");
  if (!base::WriteFile(part, body)) {
    // A write that ran out of room leaves part of a file behind, and
    // the next run would write over it anyway, but a stray .part in
    // the folder reads like a half finished update to anyone looking.
    base::DeleteFile(part);
    return false;
  }
  // Into place in one step, so a browser reading the list never finds
  // half a file there.
  if (!base::ReplaceFile(part, path, nullptr)) {
    base::DeleteFile(part);
    return false;
  }
  return true;
}

void ListUpdater::OnListSaved(bool saved) {
  if (!saved) {
    // What arrived was not what the manifest promised, or it could not
    // be put in place. Either way the list in use is left alone.
    FinishWith(kOutcomeContent);
    return;
  }
  ++next_;
  FetchNextList();
}

// static
void ListUpdater::RecordCheck(int version, bool degraded, std::string outcome) {
  const base::FilePath dir = GetDownloadedListDir();
  if (dir.empty() || !base::CreateDirectory(dir)) {
    return;
  }
  const std::string text = base::StrCat(
      {"# The time on this file is when the browser last looked for newer "
       "lists.\n",
       kMarkerVersionKey, "=", base::NumberToString(version), "\n",
       kMarkerDegradedKey, "=", degraded ? "1" : "0", "\n", kMarkerOutcomeKey,
       "=", outcome, "\n"});
  base::WriteFile(dir.Append(kMarkerFile), text);
}

// static
ListUpdater::Status ListUpdater::ReadStatus() {
  Status status;
  const base::FilePath path = MarkerPath();
  if (path.empty()) {
    return status;
  }
  const std::string text = ReadMarker();
  if (text.empty()) {
    return status;
  }
  status.checked_at = GetWrittenAt(path);
  base::StringToInt(MarkerValue(text, kMarkerVersionKey), &status.version);
  status.degraded = MarkerValue(text, kMarkerDegradedKey) == "1";
  status.outcome = MarkerValue(text, kMarkerOutcomeKey);
  return status;
}

void ListUpdater::FinishWith(std::string_view outcome) {
  // Anything other than a clean finish leaves the version on record at
  // the one still on disk, so a check that stopped part way through is
  // picked up again tomorrow instead of being written down as done.
  if (outcome != kOutcomeOk) {
    all_saved_ = false;
  }
  outcome_ = std::string(outcome);
  Finish();
}

void ListUpdater::Finish() {
  // Write down that a check happened even when it did not work, so a
  // host that is down is asked once a day and not on every new tab. The
  // version recorded is the one actually on disk, so a part finished
  // update is picked up again tomorrow.
  if (asked_) {
    base::ThreadPool::PostTask(
        FROM_HERE, {base::MayBlock(), base::TaskPriority::BEST_EFFORT},
        base::BindOnce(&ListUpdater::RecordCheck,
                       all_saved_ ? version_ : local_.version,
                       all_saved_ ? degraded_ : local_.degraded,
                       outcome_.empty() ? std::string(kOutcomeOk) : outcome_));
  }
  loader_.reset();
  factory_.reset();
  local_ = Local();
  wanted_.clear();
  manifest_.clear();
  next_ = 0;
  version_ = 0;
  degraded_ = false;
  outcome_.clear();
  asked_ = false;
  running_ = false;
}

}  // namespace boring
