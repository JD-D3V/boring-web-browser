// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/quad9_answer.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

namespace boring {

namespace {

constexpr size_t kHeaderSize = 12;
constexpr size_t kMaxLabel = 63;
constexpr size_t kMaxName = 253;
constexpr uint16_t kTypeA = 1;
constexpr uint16_t kClassIn = 1;
constexpr uint16_t kTypeOpt = 41;
constexpr uint16_t kOptionExtendedError = 15;
constexpr uint16_t kExtendedErrorFiltered = 17;
constexpr uint16_t kFlagResponse = 0x8000;
constexpr uint16_t kRcodeMask = 0x000F;
constexpr uint16_t kRcodeNameError = 3;

// Reads bytes in order and never past the end. Every read says whether it
// had the bytes, and a failed read leaves the position where it was.
class Reader {
 public:
  explicit Reader(std::string_view data) : data_(data) {}

  bool Skip(size_t n) {
    if (n > data_.size() - pos_) {
      return false;
    }
    pos_ += n;
    return true;
  }

  bool U8(uint8_t* out) {
    if (pos_ >= data_.size()) {
      return false;
    }
    *out = static_cast<uint8_t>(data_[pos_++]);
    return true;
  }

  bool U16(uint16_t* out) {
    if (data_.size() - pos_ < 2) {
      return false;
    }
    *out = static_cast<uint16_t>(
        (static_cast<uint8_t>(data_[pos_]) << 8) |
        static_cast<uint8_t>(data_[pos_ + 1]));
    pos_ += 2;
    return true;
  }

  // The next `n` bytes, and moves past them.
  bool Bytes(size_t n, std::string_view* out) {
    if (n > data_.size() - pos_) {
      return false;
    }
    *out = data_.substr(pos_, n);
    pos_ += n;
    return true;
  }

  bool AtEnd() const { return pos_ == data_.size(); }

 private:
  std::string_view data_;
  size_t pos_ = 0;
};

char Lower(char c) {
  return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
}

// Moves past a name. A compression pointer (two bytes) ends it. When `text`
// is given it gets the labels joined with dots, and a pointer is an error,
// because the question of an answer to our query is written out in full.
bool ReadName(Reader& r, std::string* text) {
  size_t total = 0;
  for (;;) {
    uint8_t len = 0;
    if (!r.U8(&len)) {
      return false;
    }
    if (len == 0) {
      return true;
    }
    if ((len & 0xC0) == 0xC0) {
      uint8_t low = 0;
      return text == nullptr && r.U8(&low);
    }
    if ((len & 0xC0) != 0 || len > kMaxLabel) {
      return false;
    }
    total += static_cast<size_t>(len) + 1;
    if (total > kMaxName + 1) {
      return false;
    }
    std::string_view label;
    if (!r.Bytes(len, &label)) {
      return false;
    }
    if (text) {
      for (char c : label) {
        text->push_back(Lower(c));
      }
      text->push_back('.');
    }
  }
}

std::string WithoutTrailingDot(std::string_view name) {
  if (!name.empty() && name.back() == '.') {
    name.remove_suffix(1);
  }
  std::string out;
  for (char c : name) {
    out.push_back(Lower(c));
  }
  return out;
}

// Looks through the options of an OPT record for Extended DNS Error with
// info code 17.
bool OptionsHoldFiltered(Reader options) {
  while (!options.AtEnd()) {
    uint16_t code = 0;
    uint16_t len = 0;
    std::string_view body;
    if (!options.U16(&code) || !options.U16(&len) ||
        !options.Bytes(len, &body)) {
      return false;
    }
    uint16_t info = 0;
    if (code == kOptionExtendedError && Reader(body).U16(&info) &&
        info == kExtendedErrorFiltered) {
      return true;
    }
  }
  return false;
}

}  // namespace

std::string BuildDnsQuery(std::string_view host) {
  std::string name = WithoutTrailingDot(host);
  if (name.empty() || name.size() > kMaxName) {
    return std::string();
  }
  std::string query(kHeaderSize, '\0');
  query[2] = 0x01;  // flags: recursion desired
  query[5] = 0x01;  // one question
  size_t start = 0;
  while (start <= name.size()) {
    size_t dot = name.find('.', start);
    if (dot == std::string::npos) {
      dot = name.size();
    }
    size_t len = dot - start;
    if (len == 0 || len > kMaxLabel) {
      return std::string();
    }
    query.push_back(static_cast<char>(len));
    query.append(name, start, len);
    start = dot + 1;
  }
  query.push_back('\0');
  query.push_back(static_cast<char>(kTypeA >> 8));
  query.push_back(static_cast<char>(kTypeA & 0xFF));
  query.push_back(static_cast<char>(kClassIn >> 8));
  query.push_back(static_cast<char>(kClassIn & 0xFF));
  return query;
}

Quad9Verdict ParseQuad9Answer(std::string_view response,
                              std::string_view host) {
  Reader r(response);
  uint16_t id = 0;
  uint16_t flags = 0;
  uint16_t questions = 0;
  uint16_t answers = 0;
  uint16_t authority = 0;
  uint16_t additional = 0;
  if (!r.U16(&id) || !r.U16(&flags) || !r.U16(&questions) ||
      !r.U16(&answers) || !r.U16(&authority) || !r.U16(&additional)) {
    return Quad9Verdict::kInvalid;
  }
  if (!(flags & kFlagResponse) || questions != 1) {
    return Quad9Verdict::kInvalid;
  }

  // The question must be the one asked, so an answer about another name
  // is never taken for this one.
  std::string asked;
  uint16_t qtype = 0;
  uint16_t qclass = 0;
  if (!ReadName(r, &asked) || !r.U16(&qtype) || !r.U16(&qclass)) {
    return Quad9Verdict::kInvalid;
  }
  if (WithoutTrailingDot(asked) != WithoutTrailingDot(host) ||
      qtype != kTypeA) {
    return Quad9Verdict::kInvalid;
  }

  // Walk every record so a cut or tangled message is invalid rather than
  // half read. Each record is at least 11 bytes, so a huge count runs out
  // of data and stops.
  const size_t total =
      static_cast<size_t>(answers) + authority + additional;
  bool filtered = false;
  for (size_t i = 0; i < total; ++i) {
    uint16_t type = 0;
    uint16_t rr_class = 0;
    uint16_t rdlength = 0;
    std::string_view rdata;
    if (!ReadName(r, nullptr) || !r.U16(&type) || !r.U16(&rr_class) ||
        !r.Skip(4) || !r.U16(&rdlength) || !r.Bytes(rdlength, &rdata)) {
      return Quad9Verdict::kInvalid;
    }
    if (type == kTypeOpt && OptionsHoldFiltered(Reader(rdata))) {
      filtered = true;
    }
  }
  if (!r.AtEnd()) {
    return Quad9Verdict::kInvalid;
  }

  const bool no_such_name = (flags & kRcodeMask) == kRcodeNameError;
  if (no_such_name && answers == 0 && authority == 0 && filtered) {
    return Quad9Verdict::kBlocked;
  }
  return Quad9Verdict::kNotBlocked;
}

}  // namespace boring
