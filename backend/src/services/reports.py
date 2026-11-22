import logging

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from redis.exceptions import RedisError

from src.config.database import connect, queue
from src.constants.domain import Role, RunState
from src.models.record import Pair
from src.services import constraints
from src.services.audit import record
from src.services.crossover import METHOD
from src.services.field import field_rows, route_or_error
from src.utils.serial import fingerprint

WAKE_KEY = 'ramp:recalculate'
LOGGER = logging.getLogger(__name__)


def create_run(plan_id, actor):
    with connect() as db:
        plan = db.execute('SELECT * FROM analysis_plan WHERE id=%s', (plan_id,)).fetchone()
        if plan is None:
            raise HTTPException(404, '未找到参数版本')
        route = route_or_error(db, plan['route_code'])
        snapshot = {
            'method': METHOD,
            'route': route,
            'plan': {'id': plan_id, 'edition': plan['edition'], 'min_pairs': plan['min_pairs'], 'gap_limit': format(plan['gap_limit'], '.2f')},
            'pairs': [Pair(**row).snapshot() for row in field_rows(db, route['code'])],
            # 冻结当前现场约束（用时范围、两轮总用时）及代际，作为缺测推演输入与时效依据。
            'rules': constraints.snapshot_rules(db, route['code']),
        }
        digest = fingerprint(snapshot)
        report = db.execute('INSERT INTO report (plan_id, created_by, snapshot, fingerprint) VALUES (%s,%s,%s,%s) '
                            'RETURNING id, state, fingerprint', (plan_id, actor, Jsonb(snapshot), digest)).fetchone()
        record(db, actor, 'run_queued', str(report['id']),
               {'fingerprint': digest, 'constraint_generation': snapshot['rules']['generation']})
    try:
        queue.lpush(WAKE_KEY, 'pending')
    except RedisError:
        LOGGER.warning('Redis wake-up failed, worker will poll PostgreSQL')
    return report


def list_reports(user):
    with connect() as db:
        rows = db.execute('''
            SELECT r.id, r.state, r.created_by AS actor, r.created_at, r.decision, p.edition, p.route_code,
                   r.snapshot->'rules'->>'generation' AS frozen_generation, c.generation AS current_generation
            FROM report AS r JOIN analysis_plan AS p ON p.id=r.plan_id
            LEFT JOIN constraint_ledger AS c ON c.route_code=p.route_code
            WHERE (%s OR r.state='published') ORDER BY r.id DESC
        ''', (user['role'] != Role.VIEWER,)).fetchall()
        for row in rows:
            row['stale'] = _is_stale(row)
        return rows


def _is_stale(row):
    frozen = row.get('frozen_generation')
    current = row.get('current_generation')
    if frozen is None or current is None:
        return False
    return int(current) > int(frozen)


def report_or_error(db, report_id, user, lock=False):
    suffix = ' FOR UPDATE' if lock else ''
    report = db.execute('''
        SELECT r.*, c.generation AS current_generation,
               r.snapshot->'rules'->>'generation' AS frozen_generation
        FROM report AS r
        LEFT JOIN analysis_plan AS p ON p.id=r.plan_id
        LEFT JOIN constraint_ledger AS c ON c.route_code=p.route_code
        WHERE r.id=%s''' + suffix, (report_id,)).fetchone()
    if report is None or (user['role'] == Role.VIEWER and report['state'] != RunState.PUBLISHED):
        raise HTTPException(404, '未找到可阅报告')
    report['stale'] = _is_stale(report)
    return report


def get_report(report_id, user):
    with connect() as db:
        return report_or_error(db, report_id, user)


def publish(report_id, review, user):
    with connect() as db:
        # 先锁报告行，再锁该路线的约束代际行并复读最新代际。
        # 仅锁报告不足以拦截“更新与发布并发”：代际来自另一张表，更新事务可能在
        # 本事务快照之后提交。锁住 ledger 行会与 bump_generation 的 UPDATE 互斥，
        # 从而保证放行前看到的是已提交的最新代际，不会发布过期结论。
        report = report_or_error(db, report_id, user, lock=True)
        if report['state'] != RunState.READY:
            raise HTTPException(409, '仅可发布已完成且待复核的报告')
        route_code = db.execute('SELECT route_code FROM analysis_plan WHERE id=%s',
                                (report['plan_id'],)).fetchone()['route_code']
        ledger = db.execute('SELECT generation FROM constraint_ledger WHERE route_code=%s FOR UPDATE',
                            (route_code,)).fetchone()
        current_generation = ledger['generation'] if ledger else 0
        stale = current_generation > int(report['frozen_generation'] or 0)
        if stale:
            record(db, user['username'], 'publish_blocked_stale', str(report_id),
                   {'frozen_generation': report['frozen_generation'],
                    'current_generation': current_generation})
            raise HTTPException(409, '现场用时规则或总用时已更新，本结论已过期，请基于新台账重新运行后再发布。')
        if review.decision not in report['result']['decisions']:
            raise HTTPException(422, '当前数据和告警状态不支持此决定')
        report = db.execute('''
            UPDATE report SET state='published', decision=%s, review_note=%s, reviewed_by=%s, reviewed_at=now()
            WHERE id=%s RETURNING *
        ''', (review.decision, review.note, user['username'], report_id)).fetchone()
        report['stale'] = False
        record(db, user['username'], 'report_published', str(report_id), review.model_dump(mode='json'))
        return report
