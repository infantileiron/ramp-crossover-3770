import csv
import os
from tempfile import NamedTemporaryFile

from src.config.settings import EXPORT_DIR


METRICS = ('complete', 'blocked', 'raw_change', 'treatment', 'period', 'sequence_gap', 'first_period', 'imbalance', 'sequence_alert')


def export_path(report_id):
    return EXPORT_DIR / f'ramp-report-{report_id}.csv'


def write_export(report_id, snapshot, fingerprint, result):
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        # Same mount as the destination so replacement is atomic across workers.
        with NamedTemporaryFile(dir=EXPORT_DIR, mode='w', encoding='utf-8-sig', newline='', delete=False) as output:
            temp = output.name
            writer = csv.writer(output)
            writer.writerow(['method', 'snapshot_sha256', 'plan_id', 'min_pairs', 'gap_limit_seconds'])
            plan = snapshot['plan']
            writer.writerow([snapshot['method'], fingerprint, plan['id'], plan['min_pairs'], plan['gap_limit']])
            writer.writerow(METRICS)
            writer.writerow([result[key] for key in METRICS])

            inference = result.get('inference')
            writer.writerow([])
            writer.writerow(['missing_inference'])
            if inference:
                writer.writerow(['status', inference['status']])
                writer.writerow(['rule_min_seconds', inference['rule_min']])
                writer.writerow(['rule_max_seconds', inference['rule_max']])
                writer.writerow(['round1_total_seconds', inference['totals'].get('1')])
                writer.writerow(['round2_total_seconds', inference['totals'].get('2')])
                writer.writerow(['missing_cells', *inference['missing_cells']])
                if inference['status'] == 'feasible':
                    writer.writerow(['treatment_min_seconds', inference['treatment_min']])
                    writer.writerow(['treatment_max_seconds', inference['treatment_max']])
                    writer.writerow(['fill_for_min', *(f"{item['code']}={item['seconds']}" for item in inference['fills']['min'])])
                    writer.writerow(['fill_for_max', *(f"{item['code']}={item['seconds']}" for item in inference['fills']['max'])])
                for reason in inference['reasons']:
                    writer.writerow(['infeasible_reason', reason])

            writer.writerow([])
            writer.writerow(['sequence', 'enrolled', 'complete', 'period1_seconds', 'period2_seconds', 'change_seconds'])
            for sequence, group in result['groups'].items():
                writer.writerow([sequence, *(group[key] for key in ('enrolled', 'complete', 'period1', 'period2', 'change'))])
            writer.writerow(['participant', 'sequence', 'period1_seconds', 'period2_seconds', 'complete'])
            for row in snapshot['pairs']:
                writer.writerow([row['code'], row['sequence'], row['period1'], row['period2'], row['period1'] is not None and row['period2'] is not None])
        os.replace(temp, export_path(report_id))
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)
