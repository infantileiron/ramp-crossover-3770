"""缺测推演：在现场补录的约束下，求补全两轮后处理差的可达上下界。

约束来源（见 002_missing_bounds.sql 与报告快照）：
  - 单人用时范围 [min_seconds, max_seconds]（用时规则，全局每格生效）；
  - 每轮全员总用时 T1、T2（可缺，表示该轮没有总用时约束）。

处理差 τ = (Δ_AB − Δ_BA) / 2，其中 Δ 序列 = 该序列（补全后）第 2 轮与
第 1 轮均值之差。τ 对每个缺测格是线性函数，且两轮的总用时约束彼此独立，
因此上下界是线性规划问题，可用闭式贪心（水填充）精确求解，无需外部求解器。
所有运算使用 Decimal，避免浮点误差影响门槛判断。
"""
from decimal import Decimal

from src.constants.domain import Sequence

ZERO = Decimal('0')


def _as_decimal(value):
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _missing_cells(pairs):
    """返回 [(code, sequence, period)]，period 为缺测的轮次（1 或 2）。"""
    cells = []
    for row in pairs:
        for period in (1, 2):
            if row.get(f'period{period}') is None:
                cells.append({'code': row['code'], 'sequence': row['sequence'], 'period': period})
    return cells


def _greedy_extreme(participants, low, high, target, maximize):
    """一轮内的线性规划极值。

    participants: [{'code', 'coef'}]，coef 为该轮缺测格在 τ 中的系数；
    变量 x_i ∈ [low, high]，若 target 非空还需 Σx_i = target。
    target 是缺测格之和的目标值（全员总用时扣除该轮已测合计后的残差）。
    maximize=True 求 Σ coef·x 的最大值，否则最小值。
    返回 (value, assignment, infeasible_reason)。assignment 为 {code: Decimal}。
    """
    n = len(participants)
    assignment = {}
    if target is None:
        # 无总用时约束：每格独立取使系数项最大/最小的端点。
        # 最大化：正系数取上限、负系数取下限；最小化反之；零系数统一下限。
        value = ZERO
        for item in participants:
            coef = item['coef']
            if coef == 0:
                pick = low
            elif maximize:
                pick = high if coef > 0 else low
            else:
                pick = low if coef > 0 else high
            assignment[item['code']] = pick
            value += coef * pick
        return value, assignment, None

    floor_sum = low * n
    ceil_sum = high * n
    if target < floor_sum:
        return None, None, f'缺测格目标合计 {target} 秒低于 {n} 个缺测格按单人下限 {low} 秒的合计 {floor_sum} 秒，无法满足。'
    if target > ceil_sum:
        return None, None, f'缺测格目标合计 {target} 秒高于 {n} 个缺测格按单人上限 {high} 秒的合计 {ceil_sum} 秒，无法满足。'

    # 起点：所有变量取下限，把剩余额度按系数贪心分配（最大化优先给大系数，
    # 最小化优先给小系数），每格最多补到 high，剩余额度恰可分配完。
    remaining = target - floor_sum
    ordered = sorted(participants, key=lambda item: item['coef'], reverse=maximize)
    values = {item['code']: low for item in ordered}
    for item in ordered:
        if remaining == 0:
            break
        room = high - low
        add = room if remaining >= room else remaining
        values[item['code']] = low + add
        remaining -= add
    # 额度一定分配完：可行性已由上面的区间检查保证。
    value = sum(item['coef'] * values[item['code']] for item in participants)
    return value, values, None


def _period_participants(cells, sequence_counts, period):
    """构造某一轮缺测格及其在 τ 中的系数。

    Δ_s = (Σp2 − Σp1)/n_s，τ = (Δ_AB − Δ_BA)/2，故单格系数为
    sign / (2 · n_s)：AB 的 p2 为 +、p1 为 −；BA 符号相反。
    """
    participants = []
    for cell in cells:
        if cell['period'] != period:
            continue
        seq = cell['sequence']
        n_seq = sequence_counts[seq]
        sign_ab = 1 if period == 2 else -1
        sign = sign_ab if seq == Sequence.AB else -sign_ab
        coef = Decimal(sign) / (2 * Decimal(n_seq))
        participants.append({'code': cell['code'], 'sequence': seq, 'coef': coef})
    return participants


def infer_bounds(snapshot):
    """对运行快照做缺测推演，返回可直接并入分析结果的字典。"""
    pairs = snapshot['pairs']
    rules = snapshot.get('rules') or {}
    low = _as_decimal(rules.get('min_seconds')) or Decimal('0.01')
    high = _as_decimal(rules.get('max_seconds')) or Decimal('900')
    # 统一字符串键：结果会经 jsonb/JSON 往返，整数键会被转成字符串。
    totals = {'1': _as_decimal(rules.get('total1')), '2': _as_decimal(rules.get('total2'))}

    cells = _missing_cells(pairs)
    result = {
        'status': 'feasible',
        'missing_cells': [f"{cell['code']}·第{cell['period']}轮" for cell in cells],
        'rule_min': low,
        'rule_max': high,
        'totals': totals,
        'treatment_min': None,
        'treatment_max': None,
        'fills': {},
        'reasons': [],
    }
    if not cells:
        result['status'] = 'no_missing'
        return result
    if low > high:
        result['status'] = 'infeasible'
        result['reasons'].append(f'用时规则下限 {low} 秒高于上限 {high} 秒，补法不存在。')
        return result

    # 补全后每序列的完整配对人数 = 当前完整数 + 该序列缺测人数（推演只补不删，
    # 已测值照用）。这与 crossover.analyze 中 Δ_s 的分母口径一致，不能用登记人数。
    sequence_counts = {}
    for seq in Sequence:
        rows = [row for row in pairs if row['sequence'] == seq]
        complete = sum(1 for row in rows if row['period1'] is not None and row['period2'] is not None)
        missing = sum(1 for row in rows if row['period1'] is None or row['period2'] is None)
        sequence_counts[seq] = complete + missing
    if any(count == 0 for count in sequence_counts.values()):
        result['status'] = 'infeasible'
        result['reasons'].append('存在未登记任何参与者的序列，无法构造两序列配对。')
        return result

    # 常数项：已测值对 τ 的贡献；缺测格贡献由贪心解给出。
    # τ = (Δ_AB − Δ_BA)/2，Δ_s=(Σp2−Σp1)/n_s，故单格系数为 sign/(2·n_s)。
    constant = ZERO
    for seq in Sequence:
        n_seq = Decimal(sequence_counts[seq])
        rows = [row for row in pairs if row['sequence'] == seq]
        for period in (1, 2):
            sign_ab = 1 if period == 2 else -1
            sign = sign_ab if seq == Sequence.AB else -sign_ab
            for row in rows:
                value = row.get(f'period{period}')
                if value is not None:
                    constant += Decimal(str(value)) * (Decimal(sign) / (2 * n_seq))

    # 逐轮处理。全员总用时包含该轮已测用时，缺测格之和的目标为
    # target = 全员总用时 − 该轮已测合计；两轮约束彼此独立。
    extremes = {}
    for period in (1, 2):
        participants = _period_participants(cells, sequence_counts, period)
        if not participants:
            continue
        total = totals[str(period)]
        target = None
        if total is not None:
            measured_sum = sum(
                (Decimal(str(row[f'period{period}'])) for row in pairs
                 if row.get(f'period{period}') is not None),
                ZERO,
            )
            target = total - measured_sum
            n_missing = len(participants)
            floor_sum = low * n_missing
            ceil_sum = high * n_missing
            if target < 0:
                result['status'] = 'infeasible'
                result['reasons'].append(
                    f'第 {period} 轮全员总用时 {total} 秒已低于该轮已测合计 {measured_sum} 秒，'
                    '缺测格不可能为负，补法不存在。'
                )
                continue
            if target < floor_sum:
                result['status'] = 'infeasible'
                result['reasons'].append(
                    f'第 {period} 轮全员总用时 {total} 秒扣除已测合计 {measured_sum} 秒后，'
                    f'缺测 {n_missing} 格需合计 {target} 秒，低于按下限 {low} 秒的合计 {floor_sum} 秒，补法不存在。'
                )
                continue
            if target > ceil_sum:
                result['status'] = 'infeasible'
                result['reasons'].append(
                    f'第 {period} 轮全员总用时 {total} 秒扣除已测合计 {measured_sum} 秒后，'
                    f'缺测 {n_missing} 格需合计 {target} 秒，高于按上限 {high} 秒的合计 {ceil_sum} 秒，补法不存在。'
                )
                continue
        for maximize in (False, True):
            value, assignment, reason = _greedy_extreme(participants, low, high, target, maximize)
            if reason is not None:
                result['status'] = 'infeasible'
                result['reasons'].append(f'第 {period} 轮：{reason}')
                continue
            extremes[(period, maximize)] = (value, assignment)

    if result['status'] == 'infeasible':
        return result

    # τ 的全局极值：各轮线性目标独立，极值之和即全局极值。
    min_value, max_value = constant, constant
    min_fill, max_fill = {}, {}
    for period in (1, 2):
        if (period, False) not in extremes:
            continue
        min_value += extremes[(period, False)][0]
        max_value += extremes[(period, True)][0]
        min_fill.update(extremes[(period, False)][1])
        max_fill.update(extremes[(period, True)][1])

    result.update(
        treatment_min=min_value,
        treatment_max=max_value,
        fills={
            'min': [{'code': code, 'seconds': min_fill[code]} for code in sorted(min_fill)],
            'max': [{'code': code, 'seconds': max_fill[code]} for code in sorted(max_fill)],
        },
    )
    return result
