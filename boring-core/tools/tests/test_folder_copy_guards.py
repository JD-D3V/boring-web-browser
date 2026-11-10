"""Folder copy safety rules (security review r3, S1 and S6).

S1: the test switch must not persist and must only take a folder under the
system temp directory. S6: a settings file that adds exception rules must
say so in the preview. These are source checks; the smoke test
(smoke_folder_copy.py) proves the behaviour in a build."""

import ast
import os
import re
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(os.path.dirname(TESTS))
FOLDER = os.path.join(CORE, "components", "boring", "folder_copy")
TOOLS = os.path.join(CORE, "tools")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def function_body(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}\n", start)]


class SwitchIsForThisRunOnly(unittest.TestCase):
    def setUp(self):
        self.cc = read(FOLDER, "folder_copy.cc")

    def test_switch_needs_a_folder_under_temp(self):
        init = function_body(self.cc, "void FolderCopy::Init()")
        self.assertIn("IsUnderTempDir(dir)", init)
        check = function_body(self.cc, "bool IsUnderTempDir(")
        self.assertIn("DIR_TEMP", check)
        self.assertIn("IsParent(dir)", check)
        self.assertIn("ReferencesParent", check)
        self.assertIn("IsAbsolute", check)

    def test_switch_refuses_network_and_non_fixed_drives(self):
        # TMP/TEMP can be pointed at a share for one run (review T4).
        local = function_body(self.cc, "bool IsOnLocalDrive(")
        self.assertIn("DRIVE_FIXED", local)
        self.assertIn("GetDriveType", local)
        check = function_body(self.cc, "bool IsUnderTempDir(")
        self.assertEqual(check.count("IsOnLocalDrive("), 2)
        self.assertIn("IsOnLocalDrive(temp)", check)
        self.assertIn("IsOnLocalDrive(dir)", check)

    def test_switch_path_never_writes_prefs(self):
        init = function_body(self.cc, "void FolderCopy::Init()")
        self.assertNotIn("SetDir(", init)
        self.assertNotIn("SetFilePath", init)
        restart = function_body(self.cc, "void FolderCopy::Restart(")
        self.assertNotIn("prefs_->Set", restart)

    def test_only_the_page_picker_writes_the_pref(self):
        sets = re.findall(r"SetFilePath\(prefs::kBoringFolderCopyDir", self.cc)
        self.assertEqual(len(sets), 1)
        set_dir = function_body(self.cc, "void FolderCopy::SetDir(")
        self.assertIn("SetFilePath(prefs::kBoringFolderCopyDir", set_dir)
        self.assertIn("test_dir_.clear()", set_dir)

    def test_armed_pref_is_not_touched_for_the_switch_folder(self):
        sets = re.findall(r"SetBoolean\(prefs::kBoringFolderCopyArmed", self.cc)
        # SetDir (off until the person says) and SetArmed (the pref branch).
        self.assertEqual(len(sets), 2)
        arm = function_body(self.cc, "void FolderCopy::SetArmed(")
        self.assertIn("test_armed_ = armed", arm)

    def test_real_users_set_the_folder_with_the_picker(self):
        ui = read(CORE, "components", "boring", "protection", "protection_ui.cc")
        self.assertIn("folder->SetDir(dir)", ui)
        self.assertNotIn("kFolderCopyDirSwitch", ui)

    def test_smoke_keeps_its_folders_under_temp_and_checks_the_rule(self):
        smoke = read(TOOLS, "smoke_folder_copy.py")
        ast.parse(smoke)
        self.assertIn("tempfile.gettempdir()", smoke)
        self.assertIn("run_outside", smoke)
        self.assertIn("saved_folder_pref", smoke)


class ExceptionRulesAreFlagged(unittest.TestCase):
    def setUp(self):
        self.cc = read(FOLDER, "folder_copy_settings.cc")

    def test_new_exception_lines_weaken(self):
        weakens = function_body(self.cc, "bool Weakens(")
        self.assertIn("Kind::kText", weakens)
        self.assertIn("AddsException(", weakens)
        adds = function_body(self.cc, "bool AddsException(")
        self.assertIn('"@@"', adds)
        self.assertIn('"#@"', adds)
        self.assertIn("old_lines.count(line)", adds)

    def test_preview_says_so_in_plain_words(self):
        self.assertIn("turn blocking off for certain sites", self.cc)
        self.assertNotIn("—", self.cc)

    def test_smoke_checks_the_wording(self):
        smoke = read(TOOLS, "smoke_folder_copy.py")
        self.assertIn("turn blocking off for certain sites (less protection)", smoke)
        self.assertIn("@@||example.org", smoke)


if __name__ == "__main__":
    unittest.main()
