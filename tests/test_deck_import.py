import io
import unittest
import zipfile

from app.deck_import import definition_from_import, preview_rows
from app.deck_import_file import read_deck_file
from app.schemas.hearthstone import DeckImportSourceRow


def workbook_xml(sheet_data, names=("Collection", "Deck"), strings="", styles=""):
    output = io.BytesIO()
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>' +
                   "".join(f'<sheet name="{name}" sheetId="{i}" r:id="r{i}"/>' for i, name in enumerate(names, 1)) + '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships>' +
                   "".join(f'<Relationship Id="r{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names)+1)) + '</Relationships>')
        for i in range(1, len(names)+1):
            data = sheet_data if names[i-1] == "Deck" or len(names) == 1 else '<row r="1"><c r="A1" t="inlineStr"><is><t>WRONG SHEET</t></is></c></row>'
            z.writestr(f"xl/worksheets/sheet{i}.xml", f'<worksheet xmlns="{main}"><sheetData>{data}</sheetData></worksheet>')
        if strings:
            z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{main}">{strings}</sst>')
        if styles:
            z.writestr("xl/styles.xml", f'<styleSheet xmlns="{main}">{styles}</styleSheet>')
    return output.getvalue()


class DeckImportTests(unittest.TestCase):
    def test_csv_bom_semicolon_multiline_editions_and_duplicate_names(self):
        content = ('\ufeffCarte (FR);Quantité;Type;Coût;Stats (ATQ/PV);Effet (résumé);Illustration;Dorée\r\n'
                   'Boule de feu;2;Sort;1;;"Effet; spécial\nligne suivante";;Oui\r\n'
                   'Boule de feu;1;Sort;;;;;Non\r\n').encode()
        preview = preview_rows(read_deck_file("deck.csv", content))
        self.assertEqual((preview["totalCount"], preview["goldenCount"]), (3, 2))
        self.assertEqual([row["source"].rowNumber for row in preview["rows"]], [2, 3])
        self.assertEqual(preview["rows"][0]["source"].text, "Effet; spécial\nligne suivante")
        self.assertEqual(preview["rows"][0]["selectedCardId"], "CS2_029")

    def test_csv_original_header_at_bottom_and_fallback(self):
        content = ('Boule de feu;1;Sort;;;Effet\nCarte (FR);Quantité;Type;Coût;Stats (ATQ/PV);Effet (résumé);Illustration\nNombre de carte dans le deck;1').encode()
        preview = preview_rows(read_deck_file("deck.csv", content))
        self.assertEqual(len(preview["rows"]), 1)
        self.assertEqual(preview["totalCount"], 1)

    def test_xlsx_chooses_deck_reads_shared_strings_rich_text_and_yellow(self):
        data = workbook_xml('<row r="3"><c r="A3" s="1" t="s"><v>0</v></c><c r="B3"><v>2</v></c><c r="E3" t="inlineStr"><is><t>3-2</t></is></c></row>',
                            strings='<si><r><t>Boule </t></r><r><t>de feu</t></r></si>',
                            styles='<fills><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFFFFF00"/></patternFill></fill></fills><cellXfs><xf fillId="0"/><xf fillId="1"/></cellXfs>')
        rows = read_deck_file("deck.xlsx", data)
        self.assertEqual(rows, [(3, ["Boule de feu", "2", "", "", "3-2", "", "", ""], True)])
        self.assertEqual(preview_rows(rows)["goldenCount"], 2)

    def test_conflicting_explicit_edition_and_yellow_fill_require_correction(self):
        row = preview_rows([(1, ["Boule de feu", "1", "Sort", "", "", "", "", "Non"], True)])["rows"][0]
        self.assertEqual(row["status"], "invalid")

    def test_google_xlsx_integer_values_written_as_decimal_numbers(self):
        data = workbook_xml('<row r="1"><c r="A1" t="inlineStr"><is><t>Boule de feu</t></is></c><c r="B1"><v>2.0</v></c><c r="D1"><v>1.0</v></c></row>')
        row = preview_rows(read_deck_file("deck.xlsx", data))["rows"][0]
        self.assertEqual(row["source"].quantity, 2)
        self.assertEqual(row["source"].cost, 1)

    def test_google_stats_automatically_converted_to_dates_keep_displayed_stats(self):
        data = workbook_xml('<row r="1"><c r="A1" t="inlineStr"><is><t>Apprentie du sorcier</t></is></c><c r="B1"><v>1.0</v></c><c r="E1" s="1"><v>45691.0</v></c></row>',
                            styles='<numFmts><numFmt numFmtId="164" formatCode="d/m"/></numFmts><fills><fill><patternFill patternType="none"/></fill></fills><cellXfs><xf fillId="0"/><xf fillId="0" numFmtId="164"/></cellXfs>')
        row = preview_rows(read_deck_file("deck.xlsx", data))["rows"][0]
        self.assertEqual((row["source"].attack, row["source"].health), (3, 2))

    def test_links_preserve_sheet_values_and_blank_catalogue_fallback(self):
        source = DeckImportSourceRow(rowNumber=1, name="Apprentie du sorcier", quantity=2, isGolden=True, cost=2, attack=3, health=2, text="Adaptation JDR", cardType="Serviteur")
        from app.routers.hearthstone import definition_values
        values = definition_values(definition_from_import(source, "EX1_608"))
        self.assertEqual((values["cost"], values["effect_text"], values["attack"]), (2, "Adaptation JDR", 3))
        self.assertEqual(values["card_type"], "MINION")
        empty = DeckImportSourceRow(rowNumber=2, name="Boule de feu")
        self.assertEqual(definition_values(definition_from_import(empty, "CS2_029"))["cost"], 4)

    def test_approximate_names_require_confirmation_and_custom_is_missing(self):
        rows = preview_rows([(1, ["Guerrier Mogushan je sais pas quoi", "1"], False), (2, ["Givrix", "1"], True)])["rows"]
        self.assertEqual(rows[0]["status"], "suggested")
        self.assertEqual(rows[0]["candidates"][0]["id"], "EX1_396")
        self.assertIsNone(rows[0]["selectedCardId"])
        self.assertEqual(rows[1]["status"], "missing")

    def test_invalid_rows_are_explained_and_original_values_retained(self):
        for quantity, stats, edition in [("-1", "", ""), ("1.5", "", ""), ("1", "3:2", ""), ("1", "", "maybe")]:
            with self.subTest(quantity=quantity, stats=stats, edition=edition):
                rows = preview_rows([(1, ["Boule de feu", quantity, "Sort", "", stats, "", "", edition], False)])["rows"]
                self.assertEqual(rows[0]["status"], "invalid")
                self.assertEqual(rows[0]["rawValues"][1], quantity)

    def test_rejects_unsafe_and_oversized_files(self):
        cases = [("deck.csv", b'"unterminated'), ("deck.csv", b'\xff'), ("deck.csv", b'x' * (2*1024*1024+1)),
                 ("deck.csv", b"x\n" * 1001), ("deck.xlsx", b"invalid"), ("deck.xls", b"x"),
                 ("deck.xlsx", workbook_xml('<row r="1001"/>')), ("deck.xlsx", workbook_xml('', names=("A", "B")))]
        for filename, data in cases:
            with self.subTest(filename=filename, size=len(data)), self.assertRaises(ValueError):
                read_deck_file(filename, data)

    def test_formulas_are_rejected_only_on_card_rows(self):
        data = workbook_xml('<row r="1"><c r="A1" t="inlineStr"><is><t>Boule de feu</t></is></c><c r="B1"><f>1+1</f><v>2</v></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>Total</t></is></c><c r="B2"><f>SUM(B1)</f><v>2</v></c></row>')
        preview = preview_rows(read_deck_file("deck.xlsx", data))
        self.assertEqual(len(preview["rows"]), 1)
        self.assertEqual(preview["rows"][0]["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
