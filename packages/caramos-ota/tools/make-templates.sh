#!/bin/bash
# Build the empty documents of right-click > "Mới" in Files (usr/share/caramos-ota/templates/<lang>/) with LibreOffice:
# a Word document (A4), an Excel workbook and a 16:9 PowerPoint deck, plus an empty text file. Run it again only when
# the templates change; the results are committed. Needs soffice (LibreOffice) on the build host.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=usr/share/caramos-ota/templates
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

doc_fodt() {  # <language> <country>: an empty A4 page whose text is in that language (spelling check)
cat <<XML
<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" office:version="1.3" office:mimetype="application/vnd.oasis.opendocument.text">
 <office:styles><style:default-style style:family="paragraph"><style:text-properties fo:language="$1" fo:country="$2"/>
 </style:default-style></office:styles>
 <office:automatic-styles>
  <style:page-layout style:name="pm1"><style:page-layout-properties fo:page-width="21cm" fo:page-height="29.7cm"
   fo:margin-top="2cm" fo:margin-bottom="2cm" fo:margin-left="3cm" fo:margin-right="2cm"/></style:page-layout>
 </office:automatic-styles>
 <office:master-styles><style:master-page style:name="Standard" style:page-layout-name="pm1"/></office:master-styles>
 <office:body><office:text><text:p/></office:text></office:body>
</office:document>
XML
}
cat > "$WORK/sheet.fods" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" office:version="1.3"
  office:mimetype="application/vnd.oasis.opendocument.spreadsheet">
 <office:body><office:spreadsheet><table:table table:name="Sheet1"><table:table-row><table:table-cell/></table:table-row>
 </table:table></office:spreadsheet></office:body>
</office:document>
XML
cat > "$WORK/deck.fodp" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"
  office:version="1.3" office:mimetype="application/vnd.oasis.opendocument.presentation">
 <office:automatic-styles>
  <style:page-layout style:name="pm1"><style:page-layout-properties fo:page-width="28cm" fo:page-height="15.75cm"
   fo:margin-top="0cm" fo:margin-bottom="0cm" fo:margin-left="0cm" fo:margin-right="0cm" style:print-orientation="landscape"/></style:page-layout>
 </office:automatic-styles>
 <office:master-styles><style:master-page style:name="Default" style:page-layout-name="pm1"/></office:master-styles>
 <office:body><office:presentation><draw:page draw:name="page1" draw:master-page-name="Default"/></office:presentation></office:body>
</office:document>
XML

convert() {  # <source> <format> <target>
  soffice -env:UserInstallation="file://$WORK/profile" --headless --convert-to "$2" --outdir "$WORK" "$WORK/$1" >/dev/null
  install -D -m 0644 "$WORK/${1%.*}.$2" "$3"
}
for lang in vi en; do
  if [[ "$lang" == vi ]]; then
    names=("Văn bản Word.docx" "Bảng tính Excel.xlsx" "Trình chiếu PowerPoint.pptx" "Tệp văn bản.txt")
    doc_fodt vi VN > "$WORK/doc.fodt"
  else
    names=("Word Document.docx" "Excel Spreadsheet.xlsx" "PowerPoint Presentation.pptx" "Text Document.txt")
    doc_fodt en US > "$WORK/doc.fodt"
  fi
  rm -rf "${OUT:?}/$lang"
  convert doc.fodt docx "$OUT/$lang/${names[0]}"
  convert sheet.fods xlsx "$OUT/$lang/${names[1]}"
  convert deck.fodp pptx "$OUT/$lang/${names[2]}"
  install -m 0644 /dev/null "$OUT/$lang/${names[3]}"
done
ls -l "$OUT"/*
