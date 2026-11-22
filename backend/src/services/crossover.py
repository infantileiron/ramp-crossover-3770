from decimal import Decimal
from statistics import mean

from src.constants.domain import Decision, Sequence
from src.services.missing_bounds import infer_bounds

METHOD = 'crossover.two-period.v1'


def summarize(rows):
    paired = [row for row in rows if row['period1'] is not None and row['period2'] is not None]
    incomplete = [row['code'] for row in rows if row['period1'] is None or row['period2'] is None]
    summary = {'enrolled': len(rows), 'complete': len(paired), 'incomplete': incomplete,
               'period1': None, 'period2': None, 'change': None, 'level': None}
    if paired:
        first = mean(Decimal(row['period1']) for row in paired)
        second = mean(Decimal(row['period2']) for row in paired)
        summary.update(period1=first, period2=second, change=second-first, level=(first+second)/2)
    return summary


def analyze(snapshot):
    settings = snapshot['plan']
    groups = {sequence: summarize([row for row in snapshot['pairs'] if row['sequence'] == sequence]) for sequence in Sequence}
    ab, ba = groups[Sequence.AB], groups[Sequence.BA]
    count = ab['complete'] + ba['complete']
    complete_groups = [group for group in groups.values() if group['complete']]
    trend = (sum(group['complete'] * group['change'] for group in complete_groups) / count) if count else None
    has_both_groups = len(complete_groups) == 2
    blocked = any(group['complete'] < settings['min_pairs'] for group in groups.values())
    gap = ba['level'] - ab['level'] if has_both_groups else None
    first_period = ba['period1'] - ab['period1'] if has_both_groups else None
    imbalanced = ab['complete'] != ba['complete']
    gap_alert = gap is not None and abs(gap) >= Decimal(settings['gap_limit'])
    treatment = (ab['change'] - ba['change']) / 2 if not blocked else None
    period = (ab['change'] + ba['change']) / 2 if not blocked else None
    # 缺测推演：基于现场补录的用时范围与每轮总用时，求补全后处理差的可达区间。
    inference = infer_bounds(snapshot)
    alerts = []
    if blocked:
        alerts.append('至少一个顺序未达到完整配对门槛，处理差和时期差暂不估计。')
    if ab['incomplete'] or ba['incomplete']:
        alerts.append('未完成两轮的参与者已从全部用时比较中剔除，缺测可能影响代表性。')
    if imbalanced:
        alerts.append('两序列完整人数不同。总体变化按人数计，处理差与时期差按序列等权计。')
    if gap_alert:
        alerts.append('两序列的双轮平均用时差达到复核线。应复核基线差异、环境变化及上一轮指引的延续影响。')
    if inference['status'] == 'infeasible':
        alerts.append('缺测补法无解：' + '；'.join(inference['reasons']))
    elif inference['status'] == 'feasible':
        alerts.append(
            f"按现场约束补全缺测后，处理差可达 {inference['treatment_min']} 至 {inference['treatment_max']} 秒，"
            '区间含已给出的极值补法。'
        )
    decisions = [Decision.RETEST, Decision.RETAIN]
    # 试挂门槛保留原有条件，并要求缺测推演区间整体严格位于零以下；
    # 无缺测时区间退化为点估计，等价于原“B 的估计用时较短”。
    if not blocked and not gap_alert and not imbalanced and treatment is not None:
        if inference['status'] == 'feasible' and inference['treatment_max'] < 0:
            decisions.append(Decision.PILOT)
        elif inference['status'] == 'no_missing' and treatment < 0:
            decisions.append(Decision.PILOT)
    return {
        'method': METHOD, 'groups': groups, 'complete': count, 'blocked': blocked,
        'raw_change': trend, 'treatment': treatment, 'period': period, 'sequence_gap': gap,
        'first_period': first_period, 'imbalance': imbalanced, 'sequence_alert': gap_alert,
        'inference': inference,
        'alerts': alerts, 'decisions': decisions,
    }
