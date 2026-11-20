// Copyright 2026 boring. BSD style license.

#include "components/boring/accounts/accounts_handler.h"

#include <optional>
#include <string>
#include <utility>

#include "base/functional/bind.h"
#include "base/values.h"
#include "components/boring/accounts/accounts_store.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/page_navigator.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/common/referrer.h"
#include "ui/base/page_transition_types.h"
#include "ui/base/window_open_disposition.h"

namespace boring::accounts {

namespace {

constexpr char kChangedEvent[] = "boring-accounts-changed";

PrefService* PrefsFor(content::WebUI* web_ui) {
  return user_prefs::UserPrefs::Get(
      web_ui->GetWebContents()->GetBrowserContext());
}

std::string ProblemText(UrlProblem problem) {
  switch (problem) {
    case UrlProblem::kNotHttps:
      return "Use an address that starts with https://";
    case UrlProblem::kCredentials:
      return "That address has a name and password in it. Use the plain "
             "address.";
    default:
      return "That does not look like a web address.";
  }
}

bool IsString(const base::ListValue& args, size_t i) {
  return i < args.size() && args[i].is_string();
}

}  // namespace

AccountsHandler::AccountsHandler() = default;
AccountsHandler::~AccountsHandler() = default;

void AccountsHandler::RegisterMessages() {
  const auto add = [this](const char* name, auto method) {
    web_ui()->RegisterMessageCallback(
        name, base::BindRepeating(method, base::Unretained(this)));
  };
  add("boringAccountsGet", &AccountsHandler::HandleGet);
  add("boringAccountsAddKnown", &AccountsHandler::HandleAddKnown);
  add("boringAccountsAddOther", &AccountsHandler::HandleAddOther);
  add("boringAccountsRename", &AccountsHandler::HandleRename);
  add("boringAccountsRemove", &AccountsHandler::HandleRemove);
  add("boringAccountsMove", &AccountsHandler::HandleMove);
}

void AccountsHandler::OnJavascriptAllowed() {
  // The panel and the new tab page change the list too.
  registrar_.Init(PrefsFor(web_ui()));
  registrar_.Add(kAccountsPref,
                 base::BindRepeating(&AccountsHandler::OnListChanged,
                                     base::Unretained(this)));
}

void AccountsHandler::OnJavascriptDisallowed() {
  registrar_.RemoveAll();
}

void AccountsHandler::OnListChanged() {
  FireWebUIListener(kChangedEvent, Answer(true));
}

bool AccountsHandler::CanWrite() {
  return !web_ui()->GetWebContents()->GetBrowserContext()->IsOffTheRecord();
}

base::DictValue AccountsHandler::Answer(bool ok) {
  const std::vector<Account> accounts = GetAccounts(*PrefsFor(web_ui()));
  base::ListValue list;
  for (const Account& account : accounts) {
    base::DictValue item;
    item.Set("id", account.id);
    item.Set("initial", Initial(account));
    item.Set("name", account.name);
    item.Set("providerLine", ProviderLine(account));
    list.Append(std::move(item));
  }
  base::DictValue out;
  out.Set("accounts", std::move(list));
  out.Set("full", accounts.size() >= kMaxAccounts);
  out.Set("ok", ok);
  return out;
}

// [callback id]
void AccountsHandler::HandleGet(const base::ListValue& args) {
  if (!IsString(args, 0)) {
    return;
  }
  AllowJavascript();
  ResolveJavascriptCallback(args[0], Answer(true));
}

// [callback id, provider]
void AccountsHandler::HandleAddKnown(const base::ListValue& args) {
  if (!IsString(args, 0) || !IsString(args, 1)) {
    return;
  }
  AllowJavascript();
  std::optional<Provider> provider = ProviderFromKey(args[1].GetString());
  bool ok = false;
  if (CanWrite() && provider && *provider != Provider::kOther &&
      AddKnown(PrefsFor(web_ui()), *provider)) {
    ok = true;
    // The company's own sign-in page, in a new tab, as from the panel.
    web_ui()->GetWebContents()->OpenURL(
        content::OpenURLParams(KnownLinks(*provider).sign_in,
                               content::Referrer(),
                               WindowOpenDisposition::NEW_FOREGROUND_TAB,
                               ui::PAGE_TRANSITION_AUTO_BOOKMARK,
                               /*is_renderer_initiated=*/false),
        /*navigation_handle_callback=*/{});
  }
  ResolveJavascriptCallback(args[0], Answer(ok));
}

// [callback id, name, mail, calendar, files]
void AccountsHandler::HandleAddOther(const base::ListValue& args) {
  if (args.size() != 5 || !IsString(args, 0) || !IsString(args, 1) ||
      !IsString(args, 2) || !IsString(args, 3) || !IsString(args, 4)) {
    return;
  }
  AllowJavascript();
  if (!CanWrite()) {
    ResolveJavascriptCallback(args[0], Answer(false));
    return;
  }
  const std::string& mail = args[2].GetString();
  const std::string& calendar = args[3].GetString();
  const std::string& files = args[4].GetString();
  const auto result = AddOther(PrefsFor(web_ui()), args[1].GetString(), mail,
                               calendar, files);
  base::DictValue out = Answer(result.has_value());
  if (!result.has_value()) {
    // Which field, and in words, why.
    GURL unused;
    std::string field;
    std::string error;
    switch (result.error()) {
      case AddError::kFull:
        error = "You have 12 accounts. Remove one to add another.";
        break;
      case AddError::kBadName:
        field = "name";
        error = "Use a shorter name.";
        break;
      case AddError::kBadMail:
        field = "mail";
        error = ProblemText(CheckOtherUrlProblem(mail, &unused));
        break;
      case AddError::kBadCalendar:
        field = "calendar";
        error = ProblemText(CheckOtherUrlProblem(calendar, &unused));
        break;
      case AddError::kBadFiles:
        field = "files";
        error = ProblemText(CheckOtherUrlProblem(files, &unused));
        break;
    }
    out.Set("field", field);
    out.Set("error", error);
  }
  ResolveJavascriptCallback(args[0], out);
}

// [callback id, id, name]
void AccountsHandler::HandleRename(const base::ListValue& args) {
  if (!IsString(args, 0) || !IsString(args, 1) || !IsString(args, 2)) {
    return;
  }
  AllowJavascript();
  const bool ok = CanWrite() && Rename(PrefsFor(web_ui()), args[1].GetString(),
                                       args[2].GetString());
  ResolveJavascriptCallback(args[0], Answer(ok));
}

// [callback id, id]
void AccountsHandler::HandleRemove(const base::ListValue& args) {
  if (!IsString(args, 0) || !IsString(args, 1)) {
    return;
  }
  AllowJavascript();
  const bool ok = CanWrite() && Remove(PrefsFor(web_ui()), args[1].GetString());
  ResolveJavascriptCallback(args[0], Answer(ok));
}

// [callback id, id, -1 | 1]
void AccountsHandler::HandleMove(const base::ListValue& args) {
  if (!IsString(args, 0) || !IsString(args, 1) || args.size() != 3 ||
      !args[2].is_int()) {
    return;
  }
  AllowJavascript();
  const bool ok = CanWrite() && Move(PrefsFor(web_ui()), args[1].GetString(),
                                     args[2].GetInt());
  ResolveJavascriptCallback(args[0], Answer(ok));
}

}  // namespace boring::accounts
