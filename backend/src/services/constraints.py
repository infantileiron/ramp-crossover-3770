from fastapi import HTTPException

from src.config.database import connect
from src.services.audit import record
from src.services.field import route_or_error


def _ensure_ledger(db, route_code):
    db.execute(
        'INSERT INTO constraint_ledger (route_code, generation) VALUES (%s, 0) ON CONFLICT (route_code) DO NOTHING',
        (route_code,),
    )


def bump_generation(db, route_code):
    """现场约束发生变化时推进代际，使冻结在旧代际的待发布结论过期。"""
    _ensure_ledger(db, route_code)
    row = db.execute(
        'UPDATE constraint_ledger SET generation = generation + 1 WHERE route_code=%s RETURNING generation',
        (route_code,),
    ).fetchone()
    return row['generation']


def current_generation(db, route_code):
    _ensure_ledger(db, route_code)
    return db.execute('SELECT generation FROM constraint_ledger WHERE route_code=%s', (route_code,)).fetchone()['generation']


def get_constraints(route_code):
    with connect() as db:
        route_or_error(db, route_code)
        rule = db.execute('SELECT min_seconds, max_seconds, updated_by, updated_at FROM timing_rule WHERE route_code=%s',
                          (route_code,)).fetchone()
        totals = db.execute('SELECT period, total_seconds, updated_by, updated_at FROM round_total WHERE route_code=%s ORDER BY period',
                            (route_code,)).fetchall()
        generation = current_generation(db, route_code)
        return {'rule': rule, 'totals': totals, 'generation': generation}


def save_rule(route_code, data, actor):
    with connect() as db:
        route_or_error(db, route_code)
        if data.min_seconds > data.max_seconds:
            raise HTTPException(422, '用时规则下限不能高于上限。')
        rule = db.execute('''
            INSERT INTO timing_rule (route_code, min_seconds, max_seconds, updated_by)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (route_code) DO UPDATE
              SET min_seconds=excluded.min_seconds, max_seconds=excluded.max_seconds,
                  updated_by=excluded.updated_by, updated_at=now()
            RETURNING min_seconds, max_seconds, updated_at
        ''', (route_code, data.min_seconds, data.max_seconds, actor)).fetchone()
        generation = bump_generation(db, route_code)
        record(db, actor, 'timing_rule_saved', route_code,
               {'min_seconds': float(data.min_seconds), 'max_seconds': float(data.max_seconds),
                'generation': generation})
        return {'rule': rule, 'generation': generation}


def save_total(route_code, period, data, actor):
    with connect() as db:
        route_or_error(db, route_code)
        row = db.execute('''
            INSERT INTO round_total (route_code, period, total_seconds, updated_by)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (route_code, period) DO UPDATE
              SET total_seconds=excluded.total_seconds, updated_by=excluded.updated_by, updated_at=now()
            RETURNING period, total_seconds, updated_at
        ''', (route_code, period, data.total_seconds, actor)).fetchone()
        generation = bump_generation(db, route_code)
        record(db, actor, 'round_total_saved', f'{route_code}/period{period}',
               {'period': period, 'total_seconds': float(data.total_seconds), 'generation': generation})
        return {'total': row, 'generation': generation}


def delete_total(route_code, period, actor):
    with connect() as db:
        route_or_error(db, route_code)
        deleted = db.execute('DELETE FROM round_total WHERE route_code=%s AND period=%s RETURNING period',
                             (route_code, period)).fetchone()
        if deleted is None:
            raise HTTPException(404, '该轮暂无总用时记录')
        generation = bump_generation(db, route_code)
        record(db, actor, 'round_total_deleted', f'{route_code}/period{period}',
               {'period': period, 'generation': generation})
        return {'generation': generation}


def snapshot_rules(db, route_code):
    """冻结进运行快照的约束内容与代际。"""
    rule = db.execute('SELECT min_seconds, max_seconds FROM timing_rule WHERE route_code=%s',
                      (route_code,)).fetchone()
    totals = {row['period']: row['total_seconds']
              for row in db.execute('SELECT period, total_seconds FROM round_total WHERE route_code=%s',
                                    (route_code,)).fetchall()}
    return {
        'min_seconds': format(rule['min_seconds'], '.2f') if rule else None,
        'max_seconds': format(rule['max_seconds'], '.2f') if rule else None,
        'total1': format(totals[1], '.2f') if 1 in totals else None,
        'total2': format(totals[2], '.2f') if 2 in totals else None,
        'generation': current_generation(db, route_code),
    }
