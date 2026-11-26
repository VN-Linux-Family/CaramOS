# Translations

Source strings in the code are English. Each folder is one gettext domain with a Vietnamese catalog:

| Domain | Used by | Source files |
|---|---|---|
| `caramos-ota` | Update Center, Audit tool, notices from the CaramOS team (`caramos_ota/notices_window.py`), Driver Check and Feedback & Help (`caramos_ota.i18n`), Feedback & Help applet, Phòng máy, the office documents dialog, the clipboard history (Super+V), Print Screen to the clipboard, Chuyển mã sang Unicode, Chuyển dữ liệu từ Windows | `usr/lib/python3/dist-packages/caramos_ota_notifier/*.py`, `caramos_ota_audit/{ui,cli}.py`, `usr/share/caramos-ota/driver-check/caramos_driver_check/**/*.py`, `usr/share/caramos-ota/lab/caramos_lab/*.py`, `usr/share/caramos-ota/open-document/caramos_open_document.py`, `usr/bin/caramos-clipboard`, `usr/bin/caramos-print-screen`, `usr/share/caramos-ota/unicode/caramos_unicode/*.py`, `usr/share/caramos-ota/windows-transfer/caramos_transfer/*.py`, `usr/share/caramos-ota/applets/caramos-help@caramos/applet.js` |
| `caramos-control-center` | Control Center: the Cinnamon applet and the Xfce edition's Control Center (one catalog, the same words) | `usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js`, `usr/share/caramos-ota/xfce/control-center/caramos_xfce_cc/**/*.py` |

`tools/caramos-ota-testkit.sh compile` (run by the package build) compiles every `po/<domain>/<lang>.po` to
`usr/share/locale/<lang>/LC_MESSAGES/<domain>.mo`, which `debian/install` ships. Build dependency: `gettext`.

After changing user-visible strings, refresh the template and merge it into `vi.po`, then translate the new
entries (no empty or fuzzy `msgstr`; the tests check this):

```bash
cd packages/caramos-ota
xgettext --language=Python --from-code=UTF-8 --keyword=_ --keyword=ngettext:1,2 \
  --package-name=caramos-ota -o po/caramos-ota/caramos-ota.pot \
  usr/lib/python3/dist-packages/caramos_ota_notifier/{ui,app,state,problem,auto_update}.py \
  usr/lib/python3/dist-packages/caramos_ota_audit/{ui,cli}.py \
  usr/lib/python3/dist-packages/caramos_ota/notices_window.py \
  $(find usr/share/caramos-ota/driver-check/caramos_driver_check -name '*.py' | sort) \
  $(find usr/share/caramos-ota/lab/caramos_lab -name '*.py' | sort) \
  usr/share/caramos-ota/open-document/caramos_open_document.py \
  usr/bin/caramos-clipboard usr/bin/caramos-print-screen \
  $(find usr/share/caramos-ota/unicode/caramos_unicode usr/share/caramos-ota/windows-transfer/caramos_transfer \
    -name '*.py' | sort)
xgettext --language=JavaScript --from-code=UTF-8 --keyword=_ --keyword=ngettext:1,2 --join-existing \
  --package-name=caramos-ota -o po/caramos-ota/caramos-ota.pot \
  usr/share/caramos-ota/applets/caramos-help@caramos/applet.js
xgettext --language=JavaScript --from-code=UTF-8 --keyword=_ --keyword=ngettext:1,2 \
  --add-comments=Translators: --package-name=caramos-control-center \
  -o po/caramos-control-center/caramos-control-center.pot \
  usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js
xgettext --language=Python --from-code=UTF-8 --keyword=_ --keyword=ngettext:1,2 --join-existing \
  --add-comments=Translators: --package-name=caramos-control-center \
  -o po/caramos-control-center/caramos-control-center.pot \
  $(find usr/share/caramos-ota/xfce/control-center/caramos_xfce_cc -name '*.py' | sort)
msgmerge --update --backup=none po/caramos-ota/vi.po po/caramos-ota/caramos-ota.pot
msgmerge --update --backup=none po/caramos-control-center/vi.po po/caramos-control-center/caramos-control-center.pot
for po in po/*/vi.po; do msgfmt --check --statistics -o /dev/null "$po"; done  # one at a time: given several files, msgfmt merges them and reports their shared strings as errors
```

Update metadata shown in the Update Center comes from each migration's `manifest.json`: `title`/`summary`/`size`
are Vietnamese and `title_en`/`summary_en`/`size_en` are shown in other languages. The App Center has its own
catalog (`caramos-app-center` domain) in its repository, `packages/caramos-app-center`.
