"""Migration 20261123120000_hidden_password_typing: Cinnamon's password boxes are passwords for the input method, so
Lotus shows nothing in clear there (ticket H-1200)."""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update import cinnamon_patches
from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).parents[1]
migration = importlib.import_module("caramos_ota_update.migrations.20261123120000_hidden_password_typing.migration")

# The part of Cinnamon 6.6.4's js/misc/inputMethod.js that the block goes into.
INPUT_METHOD_JS = """// -*- mode: js; js-indent-level: 4; indent-tabs-mode: nil -*-
/* exported InputMethod */
const { Clutter, GLib, Gio, GObject, IBus } = imports.gi;

var InputMethod = GObject.registerClass(
class InputMethod extends Clutter.InputMethod {
    vfunc_update_content_purpose(purpose) {
        let ibusPurpose = 0;
        if (purpose == Clutter.InputContentPurpose.NORMAL)
            ibusPurpose = IBus.InputPurpose.FREE_FORM;
        else if (purpose == Clutter.InputContentPurpose.DIGITS)
            ibusPurpose = IBus.InputPurpose.DIGITS;
        else if (purpose == Clutter.InputContentPurpose.PASSWORD)
            ibusPurpose = IBus.InputPurpose.PASSWORD;

        this._purpose = ibusPurpose;
        if (this._context)
            this._context.set_content_type(this._purpose, this._hints);
    }
});
"""

# Runs the patched function in node with stand-ins for Clutter, St, IBus and the stage: prints the IBus purpose sent
# for a NORMAL text in a password box, a NORMAL text that hides its letters, a plain text and a PIN-like DIGITS box.
NODE_HARNESS = """
const Clutter = { InputContentPurpose: { NORMAL: 0, DIGITS: 2, PASSWORD: 8 }, Text: class {} };
const St = { PasswordEntry: class {}, Entry: class {} };
const IBus = { InputPurpose: { FREE_FORM: 0, DIGITS: 2, PASSWORD: 8 } };
const GObject = { registerClass: klass => klass };
const imports = { gi: { Clutter, St, IBus, GObject, GLib: {}, Gio: {} } };
Clutter.InputMethod = class {};
const global = { stage: { focus: null, get_key_focus() { return this.focus; } } };
function text(parent, passwordChar) {
    const t = new Clutter.Text();
    t.password_char = passwordChar;
    t.get_parent = () => parent;
    return t;
}
%s
const im = new InputMethod();
const sent = [];
im._context = { set_content_type: (purpose, hints) => sent.push(purpose) };
for (const [focus, purpose] of [[text(new St.PasswordEntry(), 0x2022), 0], [text(new St.PasswordEntry(), 0), 0],
                                [text(new St.Entry(), 0x2022), 0], [text(new St.Entry(), 0), 0],
                                [text(new St.Entry(), 0), 2], [null, 0]]) {
    global.stage.focus = focus;
    im.vfunc_update_content_purpose(purpose);
}
console.log(JSON.stringify(sent));
"""


class PatchTests(unittest.TestCase):
    def test_the_block_goes_first_in_update_content_purpose(self) -> None:
        new = migration.patched(INPUT_METHOD_JS)
        self.assertEqual(1, new.count(migration.START))
        self.assertLess(new.index(migration.ANCHOR), new.index(migration.START))
        self.assertLess(new.index(migration.END), new.index("        let ibusPurpose = 0;"))
        self.assertEqual(INPUT_METHOD_JS, new.replace(migration.BLOCK, ""))
        self.assertEqual(new, migration.patched(new))

    def test_lines_stay_readable(self) -> None:
        for line in migration.BLOCK.splitlines():
            self.assertLessEqual(len(line), 120, line)

    def test_other_cinnamon_code_stays(self) -> None:
        changed = INPUT_METHOD_JS.replace(migration.ANCHOR, "    vfunc_update_content_purpose(purpose, hints) {\n")
        self.assertEqual("", migration.patched(changed))
        twice = INPUT_METHOD_JS + migration.ANCHOR
        self.assertEqual("", migration.patched(twice))
        half = migration.patched(INPUT_METHOD_JS).replace(migration.END, "", 1)
        self.assertEqual("", migration.patched(half))

    def test_valid_javascript(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        code = migration.patched(INPUT_METHOD_JS).replace("imports.gi;", "({});")
        subprocess.run([node, "--check", "-"], input=code, text=True, check=True, capture_output=True)

    def test_password_boxes_are_sent_as_passwords(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        source = migration.patched(INPUT_METHOD_JS).split("\n", 3)[3]  # without the header and the gi import
        result = subprocess.run([node, "-"], input=NODE_HARNESS % source, text=True, check=True,
                                capture_output=True)
        # In an St.PasswordEntry (hidden or shown) or a text hiding its letters: PASSWORD. Anywhere else, the
        # purpose Cinnamon gave stays: FREE_FORM for a plain text, DIGITS, and FREE_FORM without a focus.
        self.assertEqual([8, 8, 8, 0, 2, 0], json.loads(result.stdout))


class RestoreTests(unittest.TestCase):
    def input_method(self, text: str = INPUT_METHOD_JS) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "inputMethod.js"
        path.write_text(text, encoding="utf-8")
        path.chmod(0o644)
        return path

    def test_restore(self) -> None:
        path = self.input_method()
        with mock.patch.object(MigrationContext, "log"):
            migration.restore(MigrationContext(), path)
            migration.restore(MigrationContext(), path)
        self.assertEqual(migration.patched(INPUT_METHOD_JS), path.read_text(encoding="utf-8"))
        self.assertEqual(0o644, path.stat().st_mode & 0o777)

    def test_dry_run(self) -> None:
        path = self.input_method()
        with mock.patch.object(MigrationContext, "log"):
            migration.restore(MigrationContext(dry_run=True), path)
        self.assertEqual(INPUT_METHOD_JS, path.read_text(encoding="utf-8"))

    def test_a_file_it_does_not_know_stays(self) -> None:
        path = self.input_method("// another Cinnamon\n")
        logged: list[str] = []
        with mock.patch.object(MigrationContext, "log", side_effect=logged.append):
            migration.restore(MigrationContext(), path)
        self.assertEqual("// another Cinnamon\n", path.read_text(encoding="utf-8"))
        self.assertTrue(logged[0].startswith("warning:"), logged)

    def test_without_cinnamon(self) -> None:
        logged: list[str] = []
        with mock.patch.object(MigrationContext, "log", side_effect=logged.append):
            migration.restore(MigrationContext(), Path("/nonexistent/js/misc/inputMethod.js"))
        self.assertIn("nothing to change", logged[0])

    def test_after_a_cinnamon_update(self) -> None:
        with mock.patch.object(cinnamon_patches, "restore_taskbar"), \
                mock.patch.object(cinnamon_patches, "restore_wallpaper_collection_name"), \
                mock.patch.object(migration, "restore") as restore:
            cinnamon_patches.restore(MigrationContext(), {migration_id()})
            restore.assert_called_once()
            restore.reset_mock()
            cinnamon_patches.restore(MigrationContext(), set())
            restore.assert_not_called()
        self.assertEqual(migration_id(), cinnamon_patches.PASSWORD_MIGRATION)
        triggers = (ROOT / "debian/triggers").read_text(encoding="utf-8")
        self.assertIn(f"interest-noawait {migration.INPUT_METHOD_JS.parent}\n", triggers)

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["cinnamon"], manifest["desktops"])
        self.assertEqual("anytime", manifest["unattended"])  # nothing on the screen changes before the next login
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("đăng nhập sau", manifest["release_notes_vi"][-1])


def migration_id() -> str:
    return Path(migration.__file__).parent.name


if __name__ == "__main__":
    unittest.main()
