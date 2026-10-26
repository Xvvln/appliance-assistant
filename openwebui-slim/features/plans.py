"""Build feasible appliance combinations from the existing catalog, then explain them."""
from decimal import Decimal
from itertools import product
import json
import logging
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from open_webui.utils.auth import get_verified_user

from .common import get_shop, list_sessions, load_session, model_json, save_session

router = APIRouter(prefix='/assistant/plans', tags=['assistant-plans'])
Category = Literal['洗衣机', '空调', '冰箱']
CATEGORIES = ['洗衣机', '空调', '冰箱']
KIND = 'plans'
logger = logging.getLogger(__name__)


class Requirements(BaseModel):
    model_config = ConfigDict(extra='forbid')
    min_capacity_kg: float | None = Field(default=None, gt=0)
    requires_drying: bool | None = None
    max_installation_depth_mm: int | None = Field(default=None, gt=0)
    min_volume_l: int | None = Field(default=None, gt=0)
    horsepower: float | None = Field(default=None, gt=0)
    min_cooling_w: int | None = Field(default=None, gt=0)
    room_area_m2: float | None = Field(default=None, gt=0)

    @field_validator('horsepower', mode='before')
    @classmethod
    def parse_horsepower(cls, value):
        # The text model sometimes retains the unit from expressions such as "1.5匹".
        return value.strip().removesuffix('匹').strip() if isinstance(value, str) else value


class ConstraintPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    budget_yuan: float | None = Field(default=None, gt=0)
    categories: list[Category] | None = Field(default=None, min_length=1, max_length=3)
    requirements: dict[Category, Requirements] | None = None
    locked_models: dict[Category, str | None] | None = None
    priority: Category | None = None


class PlanRequest(BaseModel):
    message: str = Field(default='', max_length=4000)
    session_id: str | None = None
    constraints: ConstraintPatch | None = None


def merge_constraints(previous: dict, patch: dict) -> dict:
    """Apply only explicitly supplied fields; a changed budget must not drop dimensions."""
    merged = json.loads(json.dumps(previous or {
        'budget_yuan': None, 'categories': CATEGORIES.copy(), 'requirements': {},
        'locked_models': {}, 'priority': None,
    }))
    for key, value in patch.items():
        if key in ('requirements', 'locked_models'):
            if value is None:
                continue
            for category, update in value.items():
                if key == 'locked_models':
                    if update:
                        merged[key][category] = update.strip().upper()
                    else:
                        merged[key].pop(category, None)
                else:
                    current = merged[key].setdefault(category, {})
                    for field, setting in update.items():
                        if setting is None:
                            current.pop(field, None)
                        else:
                            current[field] = setting
        elif key == 'categories':
            if value:
                merged[key] = list(dict.fromkeys(value))
        else:
            merged[key] = value
    return merged


def product_rejection(item: dict, needs: dict) -> str | None:
    if item['stock'] <= 0:
        return '暂时缺货'
    category = item['category']
    if category == '洗衣机':
        if item.get('wash_kg', 0) < (needs.get('min_capacity_kg') or 0):
            return '洗涤容量不足'
        if needs.get('requires_drying') and item.get('dry_kg', 0) <= 0:
            return '不支持烘干'
    if category == '冰箱' and item.get('total_l', 0) < (needs.get('min_volume_l') or 0):
        return '总容积不足'
    if category == '空调':
        if needs.get('horsepower') and item.get('horsepower') != needs['horsepower']:
            return '匹数不符'
        if item.get('cooling_w', 0) < (needs.get('min_cooling_w') or 0):
            return '制冷量不足'
    depth = needs.get('max_installation_depth_mm')
    if depth:
        installation = item.get('installation_mm')
        if not installation or len(installation) < 3:
            return '缺少可用于核对的安装深度，需先确认安装条件'
        if installation[2] > depth:
            return f'需要预留深度 {installation[2]} mm，超过提供的 {depth} mm'
    return None


def cents(item: dict) -> int:
    return int(Decimal(str(item['price_yuan'])) * 100)


def feasible_combinations(catalog: list[dict], constraints: dict) -> tuple[list[dict], list[str], dict | None]:
    """No model-generated SKU, price, capacity or constraint relaxation enters this calculation."""
    pools = []
    problems = []
    for category in constraints['categories']:
        needs = constraints['requirements'].get(category, {})
        locked = constraints['locked_models'].get(category)
        category_items = [item for item in catalog if item['category'] == category]
        if locked:
            category_items = [item for item in category_items if item['model'] == locked]
            if not category_items:
                problems.append(f'{category}锁定型号 {locked} 不在当前目录中。')
        eligible = [item for item in category_items if product_rejection(item, needs) is None]
        if not eligible and category_items:
            reasons = list(dict.fromkeys(product_rejection(item, needs) for item in category_items))
            problems.append(f'{category}没有满足当前条件的在售型号：' + '；'.join(reasons) + '。')
        elif not eligible and not locked:
            problems.append(f'当前没有可选的{category}。')
        pools.append(eligible)
    if problems:
        return [], problems, None
    combinations = []
    for selection in product(*pools):
        total_cents = sum(cents(item) for item in selection)
        combinations.append({'id': '|'.join(item['model'] for item in selection),
                             'products': list(selection), 'total_yuan': total_cents / 100})
    combinations.sort(key=lambda combo: (combo['total_yuan'], combo['id']))
    budget = constraints.get('budget_yuan')
    if budget is None:
        return [], ['请先确定这几类家电的总预算。'], None
    valid = [combo for combo in combinations if Decimal(str(combo['total_yuan'])) <= Decimal(str(budget))]
    if not valid:
        minimum = combinations[0]['total_yuan']
        shortfall = round(minimum - budget, 2)
        return [], [f'保持当前全部条件，最低需要 ¥{minimum:g}，比预算多 ¥{shortfall:g}。请选择调整预算或哪项条件。'], {
            'minimum_total_yuan': minimum, 'shortfall_yuan': shortfall,
        }
    return valid, [], None


PARSE_INSTRUCTIONS = '''你只负责把用户明确说出的家电搭配需求转换为JSON补丁，不推荐型号，不补造要求。
返回 {"patch": {...}, "clarification": ""}。patch仅含本轮明确改变的字段，没提到的旧条件必须保留。
字段：budget_yuan(三品类合计预算元)，categories(洗衣机/空调/冰箱数组；用户明确只买哪些才改)，
requirements(按品类分类)：洗衣机min_capacity_kg、requires_drying、max_installation_depth_mm；
冰箱min_volume_l、max_installation_depth_mm；空调room_area_m2、horsepower、min_cooling_w。
所有数值字段必须输出JSON数字，不带单位，例如horsepower:1.5，不能输出"1.5匹"。
max_installation_depth_mm是用户提供的安装可用深度，单位毫米；厘米乘10。不要把商品机身深度当安装深度。
locked_models按品类填写用户明确决定保留或锁定的准确型号；明确解锁时值为null。不要把仅举例的型号锁定。
priority只在用户说优先考虑哪个品类时填写。删除某项要求用对应字段null。预算提高只改budget_yuan。
严格按输入提供的patch_schema字段结构输出；不新增type、capacity、category等别名。
requirements里的品类名是键，值必须是对象；未调整的品类直接省略，不填null或空字符串。
例如已有总预算10000，用户说“洗衣机洗烘一体至少10公斤、空调1.5匹、冰箱至少300升”时输出：
{"patch":{"requirements":{"洗衣机":{"requires_drying":true,"min_capacity_kg":10},"空调":{"horsepower":1.5},"冰箱":{"min_volume_l":300}}},"clarification":""}
每类最多一台，本功能不支持多台数量；若要求两台空调、不同房间多台等，请在clarification说明当前每类一台并询问是否分开规划，不擅自忽略。
若用户仅给面积，不从常识编造匹数。型号别名仅从给定目录匹配，不生成价格。模糊或未支持要求用clarification明确待确认，不强行编成支持字段。
只输出JSON。'''


def constraint_summary(constraints: dict) -> list[str]:
    summary = ['、'.join(constraints['categories']) + '各 1 台']
    if constraints.get('budget_yuan'):
        summary.append(f'总预算 ¥{constraints["budget_yuan"]:g}')
    names = {'min_capacity_kg': ('洗涤至少', 'kg'), 'requires_drying': ('', ''),
             'max_installation_depth_mm': ('可用安装深度', 'mm'), 'min_volume_l': ('容积至少', 'L'),
             'horsepower': ('', '匹'), 'min_cooling_w': ('制冷量至少', 'W'), 'room_area_m2': ('房间面积', '㎡')}
    for category in constraints['categories']:
        for field, value in constraints['requirements'].get(category, {}).items():
            if field == 'requires_drying':
                summary.append(f'{category}需要烘干' if value else f'{category}不要求烘干')
            else:
                prefix, unit = names[field]
                summary.append(f'{category}{prefix} {value:g}{unit}')
        if model := constraints['locked_models'].get(category):
            summary.append(f'{category}保留 {model}')
    if constraints.get('priority'):
        summary.append('优先考虑' + constraints['priority'])
    return summary


def differences(previous: dict | None, constraints: dict, plans: list[dict]) -> list[str]:
    if not previous:
        return []
    before = constraint_summary(previous['constraints'])
    after = constraint_summary(constraints)
    changes = ['取消：' + label for label in before if label not in after]
    changes += ['调整为：' + label for label in after if label not in before]
    old_plans = previous.get('plans') or []
    if old_plans and plans:
        old = old_plans[0]
        new = plans[0]
        old_models = {item['category']: item for item in old['products']}
        for item in new['products']:
            old_item = old_models.get(item['category'])
            if old_item and old_item['model'] != item['model']:
                changes.append(f'第一套方案的{item["category"]}：{old_item["name"]} → {item["name"]}')
        delta = round(new['total_yuan'] - old['total_yuan'], 2)
        if delta:
            changes.append(f'第一套方案合计{("增加" if delta > 0 else "减少")} ¥{abs(delta):g}')
    return changes


async def choose_plans(valid: list[dict], constraints: dict, message: str) -> list[dict]:
    # This catalog is small; send real feasible combinations, never ask a model to invent one.
    candidates = valid
    if len(candidates) > 90:
        candidates = [valid[round(index * (len(valid) - 1) / 89)] for index in range(90)]
    explanation = {}
    selected_ids = []
    try:
        answer = await model_json(
            '从已经核对预算、库存和可核对硬条件的组合中，选择最多3个有区别的方案。房间面积不代表已确认适用。'
            '按用户最新优先项排序，不把贵等同于好；至少保留一个省预算选项。'
            '只能选择输入中的组合id。返回JSON {"choices":[{"id":"原始id","reason":"一句取舍解释"}]}。'
            'reason只说取舍，不写价格、数量、规格数字或型号，不编造功能，不承诺安装或房间适配。',
            json.dumps({'需求': constraints, '本轮表达': message,
                        '商品': {item['model']: {key: item.get(key) for key in (
                            'category', 'name', 'features', 'tradeoff', 'price_yuan')}
                            for combo in candidates for item in combo['products']},
                        '组合': [{'id': combo['id'], 'total_yuan': combo['total_yuan'],
                                  'models': [item['model'] for item in combo['products']]}
                                 for combo in candidates]}, ensure_ascii=False))
        eligible_ids = {combo['id'] for combo in candidates}
        for choice in answer.get('choices', []):
            if not isinstance(choice, dict) or choice.get('id') not in eligible_ids:
                continue
            choice_id = choice['id']
            if choice_id in selected_ids:
                continue
            selected_ids.append(choice_id)
            reason = choice.get('reason', '')
            # Price/model/spec facts are rendered from the catalog only.
            if isinstance(reason, str) and len(reason) <= 160 and not re.search(r'[0-9￥¥]|JG-', reason, re.I):
                explanation[choice_id] = reason
            if len(selected_ids) == 3:
                break
    except Exception:
        # A failed explanation does not discard combinations already checked against actual data.
        pass
    lookup = {combo['id']: combo for combo in valid}
    minimum_id = valid[0]['id']
    if minimum_id not in selected_ids:
        if len(selected_ids) == 3:
            selected_ids[-1] = minimum_id
        else:
            selected_ids.append(minimum_id)
    for index in [len(valid) // 2, len(valid) - 1]:
        if len(selected_ids) >= 3:
            break
        choice_id = valid[index]['id']
        if choice_id not in selected_ids:
            selected_ids.append(choice_id)
    return [lookup[choice_id] | {
        'reason': explanation.get(choice_id, '在满足已确认条件的组合中保留更多预算。' if choice_id == minimum_id else '另一种满足已确认条件的搭配，可比较各品类的功能取舍。'),
        'remaining_yuan': round(constraints['budget_yuan'] - lookup[choice_id]['total_yuan'], 2),
    } for choice_id in selected_ids]


@router.get('')
def history(user=Depends(get_verified_user)):
    return {'sessions': list_sessions(user.id, KIND)}


@router.get('/{session_id}')
def restore(session_id: str, user=Depends(get_verified_user)):
    state = load_session(user.id, KIND, session_id)
    if state is None:
        raise HTTPException(404, '方案不存在。')
    return state


@router.post('')
async def update(form: PlanRequest, user=Depends(get_verified_user)):
    previous = load_session(user.id, KIND, form.session_id) if form.session_id else None
    if form.session_id and previous is None:
        raise HTTPException(404, '方案不存在。')
    catalog = get_shop()._product_catalog()
    constraints = merge_constraints(previous.get('constraints', {}) if previous else {}, {})
    if form.constraints:
        constraints = merge_constraints(constraints, form.constraints.model_dump(exclude_unset=True))
    clarification = ''
    if form.message.strip():
        try:
            parsed = await model_json(PARSE_INSTRUCTIONS, json.dumps({
                '已有条件': constraints, '用户本轮输入': form.message,
                'patch_schema': ConstraintPatch.model_json_schema(),
                '目录型号': [{'model': item['model'], 'name': item['name'], 'category': item['category']} for item in catalog],
            }, ensure_ascii=False))
            patch = ConstraintPatch.model_validate(parsed.get('patch', {})).model_dump(exclude_unset=True)
            clarification = str(parsed.get('clarification') or '')[:600]
        except ValidationError as error:
            # Only generated constraint fields are logged; no request headers, credentials or model config.
            logger.warning('plan_constraints_validation_failed: %s',
                           json.dumps(error.errors(include_url=False), ensure_ascii=False, default=str))
            raise HTTPException(422, '这次需求没有解析清楚，请把预算或要调整的条件说得更具体。') from None
        except (TypeError, ValueError) as error:
            logger.warning('plan_constraints_shape_failed: %s', str(error))
            raise HTTPException(422, '这次需求没有解析清楚，请把预算或要调整的条件说得更具体。') from None
        except Exception:
            raise HTTPException(503, '暂时无法理解这次调整，请稍后重试；原方案已保留。') from None
        constraints = merge_constraints(constraints, patch)
    if form.constraints:
        constraints = merge_constraints(constraints, form.constraints.model_dump(exclude_unset=True))
    ac = constraints['requirements'].get('空调', {})
    area_question = ''
    if '空调' in constraints['categories'] and ac.get('room_area_m2') and not (ac.get('horsepower') or ac.get('min_cooling_w')):
        area_question = (f'已记下房间面积 {ac["room_area_m2"]:g}㎡。当前资料没有适用面积区间，'
                         '不能仅凭面积确定匹数。请明确要比较的匹数或制冷量；朝向、层高和外机条件仍需安装人员核对。')
    valid, problems, no_solution = feasible_combinations(catalog, constraints)
    plans = await choose_plans(valid, constraints, form.message) if valid and not clarification else []
    notes = []
    if area_question:
        notes.append('以下空调是预算内候选，尚未确认是否适合该房间。')
    if any(req.get('max_installation_depth_mm') for req in constraints['requirements'].values()):
        notes.append('已按资料中的预留深度筛选；宽高、开门、管线和搬运条件仍需分别核对。')
    if '空调' in constraints['categories']:
        notes.append('空调按已确认的匹数或制冷量比较，房间面积、朝向、层高和安装条件需现场核对。')
    state = {'constraints': constraints, 'summary': constraint_summary(constraints), 'plans': plans,
             'differences': differences(previous, constraints, plans),
             'clarification': clarification or area_question, 'problems': problems, 'no_solution': no_solution,
             'notes': notes, 'message': form.message.strip(),
             'title': (previous or {}).get('title') or (form.message.strip()[:50] or '家电搭配方案')}
    if previous:
        state['id'] = previous['id']
        state['created_at'] = previous['created_at']
    return save_session(user.id, KIND, state)
