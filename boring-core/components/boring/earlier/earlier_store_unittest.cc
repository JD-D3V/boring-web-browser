// Copyright 2026 boring. BSD style license.

#include "components/boring/earlier/earlier_store.h"

#include "testing/gtest/include/gtest/gtest.h"

namespace boring::earlier {

namespace {

EarlierEntry Make(const std::string& id, const std::string& url) {
  EarlierEntry e;
  e.id = id;
  e.url = GURL(url);
  e.title = u"A title";
  e.moved = base::Time::FromMillisecondsSinceUnixEpoch(1700000000000);
  e.last_used = base::Time::FromMillisecondsSinceUnixEpoch(1699990000000);
  e.navigations = {{GURL("https://a.example/"), u"A"}, {e.url, u"B"}};
  e.selected_index = 1;
  return e;
}

}  // namespace

TEST(EarlierStoreTest, RoundTrip) {
  std::vector<EarlierEntry> in = {Make("a", "https://b.example/x"),
                                  Make("b", "http://c.example/")};
  ParseResult out = ParseEarlierFile(SerializeEarlierFile(in));
  ASSERT_EQ(out.status, ParseStatus::kOk);
  ASSERT_EQ(out.entries.size(), 2u);
  EXPECT_EQ(out.entries[0].id, "a");
  EXPECT_EQ(out.entries[0].url, GURL("https://b.example/x"));
  EXPECT_EQ(out.entries[0].selected_index, 1);
  EXPECT_EQ(out.entries[0].navigations.size(), 2u);
  EXPECT_EQ(out.entries[0].moved, in[0].moved);
}

TEST(EarlierStoreTest, NewerVersionIsFlagged) {
  ParseResult out = ParseEarlierFile(R"({"version": 2, "entries": []})");
  EXPECT_EQ(out.status, ParseStatus::kNewer);
}

TEST(EarlierStoreTest, CorruptIsFlagged) {
  EXPECT_EQ(ParseEarlierFile("not json").status, ParseStatus::kCorrupt);
  EXPECT_EQ(ParseEarlierFile("{}").status, ParseStatus::kCorrupt);
  EXPECT_EQ(ParseEarlierFile(R"({"version":1})").status,
            ParseStatus::kCorrupt);
}

TEST(EarlierStoreTest, UnusableEntriesAreSkipped) {
  std::vector<EarlierEntry> in = {Make("a", "https://ok.example/"),
                                  Make("b", "javascript:alert(1)"),
                                  Make("c", "chrome://settings/"),
                                  Make("a", "https://dup.example/")};
  ParseResult out = ParseEarlierFile(SerializeEarlierFile(in));
  ASSERT_EQ(out.entries.size(), 1u);
  EXPECT_EQ(out.entries[0].url, GURL("https://ok.example/"));
}

TEST(EarlierStoreTest, ListIsCut) {
  std::vector<EarlierEntry> in;
  for (size_t i = 0; i < kMaxEntries + 20; ++i) {
    in.push_back(Make("id" + std::to_string(i), "https://x.example/"));
  }
  EXPECT_EQ(ParseEarlierFile(SerializeEarlierFile(in)).entries.size(),
            kMaxEntries);
}

TEST(EarlierStoreTest, Expiry) {
  const base::Time now = base::Time::Now();
  std::vector<EarlierEntry> list = {Make("a", "https://x.example/"),
                                    Make("b", "https://y.example/")};
  list[0].moved = now - base::Days(31);
  list[1].moved = now - base::Days(29);
  EXPECT_EQ(RemoveExpired(&list, now, base::Days(30)), 1u);
  ASSERT_EQ(list.size(), 1u);
  EXPECT_EQ(list[0].id, "b");
}

TEST(EarlierStoreTest, FutureTimesExpire) {
  const base::Time now = base::Time::Now();
  std::vector<EarlierEntry> list = {Make("a", "https://x.example/"),
                                    Make("b", "https://y.example/"),
                                    Make("c", "https://z.example/")};
  list[0].moved = now + base::Days(2);
  list[1].moved = now - base::Days(1);
  list[1].last_used = now + base::Hours(1);
  list[2].moved = now - base::Days(1);
  list[2].last_used = now - base::Days(2);
  EXPECT_EQ(RemoveExpired(&list, now, base::Days(30)), 2u);
  ASSERT_EQ(list.size(), 1u);
  EXPECT_EQ(list[0].id, "c");
}

TEST(EarlierStoreTest, SwitchesOnlyShortenWithWholeSeconds) {
  std::string five = "5", bad = "abc", zero = "0";
  EarlierLimits l = LimitsFromSwitchValues(&five, &bad, &zero, nullptr);
  EXPECT_EQ(l.idle, base::Seconds(5));
  EXPECT_EQ(l.keep, base::Days(30));
  EXPECT_EQ(l.check, base::Minutes(10));
  EXPECT_EQ(l.settle, base::Minutes(10));
  // Longer than shipped is clamped to the shipped limit.
  std::string long_time = "100000000";
  l = LimitsFromSwitchValues(&long_time, &long_time, &long_time, &long_time);
  EXPECT_EQ(l.idle, base::Days(1));
  EXPECT_EQ(l.keep, base::Days(30));
  EXPECT_EQ(l.check, base::Minutes(10));
  EXPECT_EQ(l.settle, base::Minutes(10));
}

TEST(EarlierStoreTest, CleanTitleIsOneLine) {
  EXPECT_EQ(CleanTitle(u"a\n\tb   c\x01"), u"a b c");
}

}  // namespace boring::earlier
