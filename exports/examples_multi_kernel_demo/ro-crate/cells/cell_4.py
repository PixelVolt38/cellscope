# downstream analysis using both shared data and file reads
import json
from pathlib import Path

json_path = Path('data_outputs/climate_summary.json')
if json_path.exists():
    summary_records = json.loads(json_path.read_text())
else:
    summary_records = []

report = {
    'summary': climate_summary,
    'shared_records': summary_records,
    'notes': 'Derived in Cell 4'
}
report_path = Path('reports/climate_report.txt')
report_path.parent.mkdir(exist_ok=True)
report_path.write_text(str(report), encoding='utf-8')
print('report saved to', report_path)
