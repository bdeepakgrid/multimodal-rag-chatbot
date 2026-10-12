#!/usr/bin/env python3
"""Generate sample Excel fixture for tests."""
from pathlib import Path

import openpyxl

FIXTURES = Path(__file__).parent
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Maintenance Log"
ws.append(["Machine ID", "Error Code", "Description", "Resolution", "Date"])
ws.append(["M-42", "E-2047", "Motor overheating", "Check coolant flow, reduce load to 80%", "2024-01-15"])
ws.append(["M-42", "E-1102", "Bearing vibration high", "Replace bearing BR-4421", "2024-02-03"])
ws.append(["M-17", "E-3301", "Hydraulic pressure low", "Inspect pump seal, refill fluid", "2024-03-10"])
out = FIXTURES / "maintenance_log.xlsx"
wb.save(out)
print(f"Created {out}")
