# Translations

Source strings in the code are English. Each folder is one gettext domain with a Vietnamese catalog:

| Domain | Used by | Source files |
|---|---|---|
| `caramos-ota` | Update Center, Audit tool (`caramos_ota.i18n`) | `usr/lib/python3/dist-packages/caramos_ota_notifier/*.py`, `caramos_ota_audit/{ui,cli}.py` |
| `caramos-control-center` | Control Center applet | `usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js` |

`tools/caramos-ota-testkit.sh compile` (run by the package build) compiles every `po/<domain>/<lang>.po` to
`usr/share/locale/<lang>/LC_MESSAGES/<domain>.mo`, which `debian/install` ships. Build dependency: `gettext`.

After changing user-visible strings, refresh the template and merge it into `vi.po`, then translate the new
entries (no empty or fuzzy `msgstr`; the tests check this):

```bash
cd packages/caramos-ota
xgettext --language=Python --from-code=UTF-8 --keyword=_ --keyword=ngettext:1,2 \
  --package-name=caramos-ota -o po/caramos-ota/caramos-ota.pot \
  usr/lib/python3/dist-packages/caramos_ota_notifier/{ui,app,state}.py \
  usr/lib/python3/dist-packages/caramos_ota_audit/{ui,cli}.py
xgettext --language=JavaScript --from-code=UTF-8 --keyword=_ --keyword=ngettext:1,2 \
  --add-comments=Translators: --package-name=caramos-control-center \
  -o po/caramos-control-center/caramos-control-center.pot \
  usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js
msgmerge --update --backup=none po/caramos-ota/vi.po po/caramos-ota/caramos-ota.pot
msgmerge --update --backup=none po/caramos-control-center/vi.po po/caramos-control-center/caramos-control-center.pot
msgfmt --check --statistics -o /dev/null po/*/vi.po
```

Update metadata shown in the Update Center comes from each migration's `manifest.json`: `title`/`summary`
are Vietnamese and `title_en`/`summary_en` are shown in other languages.
