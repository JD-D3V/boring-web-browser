// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ACCOUNTS_ACCOUNTS_HANDLER_H_
#define COMPONENTS_BORING_ACCOUNTS_ACCOUNTS_HANDLER_H_

#include "base/values.h"
#include "components/prefs/pref_change_registrar.h"
#include "content/public/browser/web_ui_message_handler.h"

namespace boring::accounts {

// Answers Settings, Accounts (chrome://settings/accounts). Every check is
// in accounts_store; the page only shows what comes back. The page names
// accounts by id and never hands over an address for a known company.
// Each call resolves with the list as it now is, so the page never keeps a
// copy of its own.
//
//   boringAccountsGet() -> {accounts: [...], full}
//   boringAccountsAddKnown(provider) -> {accounts, full, ok}
//       Also opens that company's sign-in page in a new tab, as the
//       toolbar panel does.
//   boringAccountsAddOther(name, mail, calendar, files)
//       -> {accounts, full, ok, field, error}
//   boringAccountsRename(id, name), boringAccountsRemove(id),
//   boringAccountsMove(id, -1 | 1) -> {accounts, full, ok}
//
// Each account: {id, initial, name, providerLine}.
// The list also changes from the toolbar panel and the new tab page; the
// page hears of it as the "boring-accounts-changed" event.
class AccountsHandler : public content::WebUIMessageHandler {
 public:
  AccountsHandler();
  ~AccountsHandler() override;

  AccountsHandler(const AccountsHandler&) = delete;
  AccountsHandler& operator=(const AccountsHandler&) = delete;

  // content::WebUIMessageHandler:
  void RegisterMessages() override;
  void OnJavascriptAllowed() override;
  void OnJavascriptDisallowed() override;

 private:
  void HandleGet(const base::ListValue& args);
  void HandleAddKnown(const base::ListValue& args);
  void HandleAddOther(const base::ListValue& args);
  void HandleRename(const base::ListValue& args);
  void HandleRemove(const base::ListValue& args);
  void HandleMove(const base::ListValue& args);
  void OnListChanged();

  // The list and whether it is full, plus `ok`.
  base::DictValue Answer(bool ok);
  // Nothing is written from a guest window.
  bool CanWrite();

  PrefChangeRegistrar registrar_;
};

}  // namespace boring::accounts

#endif  // COMPONENTS_BORING_ACCOUNTS_ACCOUNTS_HANDLER_H_
