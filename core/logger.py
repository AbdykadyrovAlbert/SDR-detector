from __future__ import annotations

import csv
import html
import json
import zipfile
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Mapping


class EventLogger:
    """Сохраняет события обнаружения в CSV, JSONL и XLSX внутри папки logs/."""

    FIELDNAMES = [
        "start_time_s",
        "end_time_s",
        "duration_s",
        "center_freq_hz",
        "bandwidth_hz",
        "peak_power_db",
        "mean_power_db",
    ]

    def __init__(self, logs_dir: str | Path = "logs", prefix: str = "events") -> None:
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_path = self.logs_dir / f"{prefix}_{stamp}.csv"
        self.jsonl_path = self.logs_dir / f"{prefix}_{stamp}.jsonl"
        self.xlsx_path = self.logs_dir / f"{prefix}_{stamp}.xlsx"
        self._rows: List[Mapping] = []

        with self.csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
            writer.writeheader()

        self.jsonl_path.touch()

    def write_event(self, event) -> None:
        row = self._to_plain_dict(event)
        clean_row = {name: row.get(name, "") for name in self.FIELDNAMES}
        self._rows.append(clean_row)

        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
            writer.writerow(clean_row)

        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def write_events(self, events: Iterable) -> None:
        for event in events:
            self.write_event(event)

    def finalize(self) -> None:
        """Формирует XLSX с отдельными колонками по всем записанным событиям."""

        self._write_xlsx()

    def _to_plain_dict(self, event) -> Mapping:
        if is_dataclass(event):
            return asdict(event)
        if isinstance(event, Mapping):
            return event
        raise TypeError(f"Неизвестный тип события: {type(event)!r}")

    def _write_xlsx(self) -> None:
        rows_xml = [self._xlsx_row(1, self.FIELDNAMES)]
        for index, row in enumerate(self._rows, start=2):
            rows_xml.append(self._xlsx_row(index, [row.get(name, "") for name in self.FIELDNAMES]))

        sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <cols>
    <col min="1" max="7" width="18" customWidth="1"/>
  </cols>
  <sheetData>
    {''.join(rows_xml)}
  </sheetData>
</worksheet>"""

        workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="events" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

        workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""

        root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""

        with zipfile.ZipFile(self.xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types.encode("utf-8"))
            archive.writestr("_rels/.rels", root_rels.encode("utf-8"))
            archive.writestr("xl/workbook.xml", workbook_xml.encode("utf-8"))
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels.encode("utf-8"))
            archive.writestr("xl/worksheets/sheet1.xml", sheet_xml.encode("utf-8"))

    def _xlsx_row(self, row_index: int, values: Iterable) -> str:
        cells = []
        for column_index, value in enumerate(values, start=1):
            cell_ref = f"{self._excel_column(column_index)}{row_index}"
            if isinstance(value, (int, float)) and value != "":
                cells.append(f'<c r="{cell_ref}"><v>{value}</v></c>')
            else:
                escaped = html.escape(str(value), quote=True)
                cells.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{escaped}</t></is></c>')
        return f'<row r="{row_index}">{"".join(cells)}</row>'

    def _excel_column(self, index: int) -> str:
        result = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result
