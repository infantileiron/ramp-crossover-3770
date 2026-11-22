from typing import Annotated

from fastapi import APIRouter, Depends, Path

from src.constants.domain import Role
from src.schemas.inputs import PairCode, PairInput, PlanInput, RoundTotalInput, RouteCode, TimingRuleInput
from src.services import constraints, field
from src.services.auth import allow, current_user

router = APIRouter()
Period = Annotated[int, Path(ge=1, le=2)]


@router.get('/routes')
def routes(_=Depends(current_user)):
    return field.routes()


@router.get('/routes/{route_code}/pairs')
def pairs(route_code: RouteCode, _=Depends(current_user)):
    return field.pairs(route_code)


@router.put('/routes/{route_code}/pairs/{code}')
def save_pair(route_code: RouteCode, code: PairCode, data: PairInput, user=Depends(allow(Role.ANALYST))):
    # 现场补录仅写台账，短事务独立提交，不等待任何后台分析计算。
    return field.save_pair(route_code, code, data, user['username'])


@router.get('/routes/{route_code}/plans')
def plans(route_code: RouteCode, _=Depends(current_user)):
    return field.plans(route_code)


@router.post('/plans', status_code=201)
def create_plan(data: PlanInput, user=Depends(allow(Role.ANALYST))):
    return field.create_plan(data, user['username'])


@router.get('/routes/{route_code}/constraints')
def get_constraints(route_code: RouteCode, _=Depends(current_user)):
    return constraints.get_constraints(route_code)


@router.put('/routes/{route_code}/timing-rule')
def save_timing_rule(route_code: RouteCode, data: TimingRuleInput, user=Depends(allow(Role.ANALYST))):
    return constraints.save_rule(route_code, data, user['username'])


@router.put('/routes/{route_code}/round-totals/{period}')
def save_round_total(route_code: RouteCode, period: Period, data: RoundTotalInput,
                     user=Depends(allow(Role.ANALYST))):
    return constraints.save_total(route_code, period, data, user['username'])


@router.delete('/routes/{route_code}/round-totals/{period}', status_code=200)
def delete_round_total(route_code: RouteCode, period: Period, user=Depends(allow(Role.ANALYST))):
    return constraints.delete_total(route_code, period, user['username'])
