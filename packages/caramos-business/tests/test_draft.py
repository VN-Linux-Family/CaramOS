"""The admin window's draft (caramos_business.draft): modes per scope, defaults only when switched on, departments,
members, Wi-Fi passwords and what goes to the helper."""

from __future__ import annotations

import unittest

from caramos_business import draft, presets, protocol

MACHINE = "11111111-2222-4333-8444-555555555555"


def policy() -> dict:
    return {"format": 2, "serial": 3, "files": {"a" * 64: {"size": 1, "type": "jpg"}},
            "settings": {"usb": {"storage": "read-only"},
                         "wifi": [{"ssid": "CongTy", "security": "wpa-psk", "hidden": False}]},
            "departments": {"ke-toan": {"name": "Kế toán", "settings": {"usb": {"storage": "block"}}},
                            "kho": {"name": "Kho"}},
            "members": {MACHINE: "ke-toan"},
            "machines": {MACHINE: {"settings": {"screen_lock": {"idle_minutes": 5, "on_suspend": True}},
                                   "sealed": "x"}}}


class DraftTests(unittest.TestCase):
    def test_nothing_is_on_by_default(self) -> None:
        empty = draft.Draft({"format": 2, "serial": 0})
        for section in protocol.SECTIONS:
            with self.subTest(section):
                self.assertEqual(draft.OFF, empty.mode(draft.COMPANY, section))
                self.assertEqual(draft.INHERIT, empty.mode("department:x", section))
        self.assertFalse(empty.dirty)
        self.assertEqual({"settings": {}, "departments": {}, "members": {}, "machines": {}, "pictures": {},
                          "wifi_passphrases": {}}, empty.payload())

    def test_reading_is_not_a_change(self) -> None:
        current = draft.Draft(policy())
        for scope in (draft.COMPANY, "department:kho", "department:ke-toan", f"machine:{MACHINE}"):
            for section in protocol.SECTIONS:
                current.mode(scope, section)
                current.above(scope, section)
        self.assertFalse(current.dirty)
        self.assertNotIn("sealed", current.payload()["machines"][MACHINE])

    def test_modes(self) -> None:
        current = draft.Draft(policy())
        self.assertEqual(draft.OWN, current.mode(draft.COMPANY, "usb"))
        self.assertEqual(draft.OWN, current.mode("department:ke-toan", "usb"))
        self.assertEqual(draft.INHERIT, current.mode("department:kho", "usb"))
        self.assertEqual(({"storage": "read-only"}, "company"), current.above("department:kho", "usb"))
        self.assertEqual(({"storage": "block"}, "department:ke-toan"), current.above(f"machine:{MACHINE}", "usb"))
        self.assertEqual((None, None), current.above("department:kho", "browser"))
        current.switch("department:kho", "usb", draft.OFF)
        self.assertEqual((draft.OFF, None), (current.mode("department:kho", "usb"), current.get("department:kho", "usb")))
        current.switch("department:kho", "usb", draft.OWN)  # starts from the company's
        self.assertEqual({"storage": "read-only"}, current.get("department:kho", "usb"))
        current.switch("department:kho", "usb", draft.INHERIT)
        self.assertFalse(current.dirty)
        current.switch(draft.COMPANY, "usb", draft.OFF)  # the company: not managed at all
        self.assertFalse(current.has(draft.COMPANY, "usb"))
        current.switch(f"machine:{MACHINE}", "screen_lock", draft.INHERIT)
        self.assertNotIn(MACHINE, current.payload()["machines"], "an empty machine layer goes")

    def test_defaults_only_when_switched_on(self) -> None:
        current = draft.Draft({"format": 2, "serial": 0})
        current.switch(draft.COMPANY, "browser", draft.OWN)
        self.assertEqual(presets.OFFICE_HOURS, current.get(draft.COMPANY, "browser")["block_hours"])
        self.assertEqual([], current.get(draft.COMPANY, "browser")["block"])
        current.switch(draft.COMPANY, "power", draft.OWN)
        self.assertEqual("18:30", current.get(draft.COMPANY, "power")["shutdown"]["time"])
        self.assertEqual(["browser", "power"], sorted(current.payload()["settings"]))
        for section in protocol.SECTIONS:
            with self.subTest(section):
                value = draft.defaults(section)
                files = {}
                if section == "folders":
                    value["share"] = "smb://nas/nhanvien/%u"
                protocol.validate_settings({section: value}, files)

    def test_departments_and_members(self) -> None:
        current = draft.Draft(policy())
        self.assertEqual("ke-toan-2", current.add_department("Kế Toán 2") and "ke-toan-2")
        self.assertEqual("phong-hanh-chinh-nhan-su", current.add_department("Phòng Hành chính – Nhân sự"))
        self.assertEqual("dao-tao", current.add_department("Đào tạo"))
        with self.assertRaises(protocol.ProtocolError):
            current.add_department("kế toán")
        with self.assertRaises(protocol.ProtocolError):
            current.add_department(" ")
        current.rename_department("kho", "Kho hàng")
        self.assertEqual("Kho hàng", current.scope_title("department:kho"))
        current.remove_department("ke-toan")
        self.assertIsNone(current.department_of(MACHINE))
        current.set_department(MACHINE, "kho")
        self.assertEqual("kho", current.payload()["members"][MACHINE])
        self.assertEqual("ke-toan", draft.slug("Kế toán"))
        self.assertEqual("phong", draft.slug("!!!"))

    def test_wifi_passwords(self) -> None:
        current = draft.Draft(policy())
        self.assertEqual("saved", current.password_state("CongTy"))
        current.set(draft.COMPANY, "wifi", [{"ssid": "CongTy", "security": "wpa-psk", "hidden": False},
                                            {"ssid": "Kho", "security": "wpa-psk", "hidden": False},
                                            {"ssid": "Khach", "security": "open", "hidden": False}])
        self.assertEqual(("missing", "open"), (current.password_state("Kho"), current.password_state("Khach")))
        with self.assertRaises(protocol.ProtocolError) as caught:
            current.validate()
        self.assertEqual("wifi", caught.exception.section)
        current.passphrases["Kho"] = "matkhau-kho-123"
        current.passphrases["Cu"] = "matkhau-cu-1234"
        current.validate()
        self.assertEqual({"Kho": "matkhau-kho-123"}, current.payload()["wifi_passphrases"])

    def test_pictures_and_validation(self) -> None:
        current = draft.Draft(policy())
        name = current.new_picture("/home/minh/tet.jpg")
        unused = current.new_picture("/home/minh/old.jpg")
        current.set(draft.COMPANY, "wallpaper", {"default": name, "periods": [], "lock": True})
        current.validate()
        self.assertEqual({name: "/home/minh/tet.jpg"}, current.payload()["pictures"])
        self.assertNotIn(unused, current.payload()["pictures"])
        current.set("department:kho", "browser", dict(draft.defaults("browser"), block=["https://x.vn/a"]))
        with self.assertRaises(protocol.ProtocolError) as caught:
            current.validate()
        self.assertEqual(("browser", "department:kho"), (caught.exception.section, caught.exception.scope))


if __name__ == "__main__":
    unittest.main()
