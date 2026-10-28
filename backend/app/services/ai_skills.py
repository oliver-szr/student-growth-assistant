"""Explicit action tags, model-selected skills and code-owned tool policy.

The deterministic selector is also the offline fallback. Model decisions choose
only a fixed business capability; neither path can confirm or save formal facts.
"""
import hashlib
import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .claude_client import AIServiceError
from . import claude_client, ai_diagnostics as trace

SKILL_ROOT = Path(__file__).resolve().parents[1] / 'skills'
READ_TOOLS = frozenset({'tasks', 'goals', 'preferences', 'calendar', 'review', 'memories'})
CAPABILITIES = {
    'schedule': READ_TOOLS | {'planning_draft', 'edit_draft'},
    'task': READ_TOOLS | {'planning_draft', 'breakdown_draft', 'profile_draft', 'feedback_draft', 'edit_draft'},
    'review': READ_TOOLS | {'review_draft', 'edit_draft'},
    'memory': frozenset({'memories', 'preferences', 'memory_suggestion'}),
    'query': READ_TOOLS,
    'chat': frozenset(),
}
RESULT_KIND = {'schedule': 'planning', 'task': 'breakdown', 'create_task': 'planning',
    'profile': 'profile', 'feedback': 'feedback', 'review': 'review_record', 'memory': 'memory'}
WRITE_TOOL = {'planning': 'planning_draft', 'breakdown': 'breakdown_draft',
    'profile': 'profile_draft', 'feedback': 'feedback_draft', 'review_record': 'review_draft', 'memory': 'memory_suggestion'}
MAX_SKILL_CHARACTERS = 9000
ACTION_TAGS = {'生成草案': ('schedule', 'planning_draft'), '查看日程': ('query', 'calendar'),
    '日程': ('query', 'calendar'), '复盘': ('review', 'review_draft')}


@dataclass(frozen=True)
class Selection:
    names: tuple[str, ...]
    operation: str
    allowed: frozenset[str]
    expected: str | None = None
    reason: str = 'current_message'

    def audit(self):
        return {'version': 1, 'names': ['core', *self.names], 'operation': self.operation,
            'allowed_tools': sorted(self.allowed), 'expected_kind': self.expected, 'reason': self.reason}


def active_text(text):
    # Quotes/code are evidence to discuss, not new instructions. A quoted task
    # name can still be supplied to the model in the original bounded request.
    return re.sub(r'```[\s\S]*?```|`[^`]*`|“[^”]*”|「[^」]*」|‘[^’]*’|"[^"\n]*"', '', text).strip()


def action_tag(text):
    match = re.search(r'(?:^|\s)[#＃](生成草案|查看日程|日程|复盘)\s*$', active_text(text))
    return match[1] if match else None


def message_text(text):
    tag = action_tag(text)
    return re.sub(r'(?:^|\s)[#＃]' + tag + r'\s*$', '', text).rstrip() if tag else text


def task_statement(text):
    """A user's concrete intended activity can start an editable draft."""
    clause = re.split(r'[，,。；;！？!?\n]', text)[0].strip()
    if re.search(r'什么|怎么|如何|是否|要不要|能不能|哪里|哪儿|[吗呢么]', clause):
        return False
    day = r'(?:今天|今晚|明天|明晚|后天|本周|这周|下周|周[一二三四五六日天]|星期[一二三四五六日天])(?:早上|上午|中午|下午|晚上)?'
    subject = rf'(?:我(?:{day})?|{day}(?:我)?)'
    return bool(re.match(subject + rf'(?:要|需要|得|打算|准备|计划|想要)(?:{day})?'
        r'(?:写|做|完成|提交|制作|准备|复习|学习|阅读|练习|整理|处理|参加|去)', clause))


def _operation(text):
    if re.search(r'(删除|停用|忘掉|修改|更新|不再记住).*(记忆|习惯)|^(删除|停用|忘掉).*(偏好)', text):
        return 'manage_memory'
    if re.search(r'(创建|新建|新增|修改|调整|更新|生成|给我).*(目标|偏好|档案)|生成目标建议|希望.*(每周|周[一二三四五六日]).*(留空|避开)', text):
        return 'profile'
    if re.search(r'(记住|记下|以后|今后|长期偏好).*(偏好|喜欢|学习|例子|结论|拆|请|希望)|^(请)?记住', text):
        return 'memory'
    if re.search(r'(拆解|拆成|修改草案|保留\d+分钟|分成.{0,8}(步骤|任务)|列.{0,3}计划)', text):
        return 'task'
    if re.search(r'(复盘一下|帮我复盘|一起复盘|总结一下|总结本|整理.{0,12}复盘|生成.{0,8}复盘|复盘.{0,5}初稿)', text):
        return 'review'
    if re.search(r'(反馈|记录).*(完成|投入|分钟|执行)|修正执行|反馈草案|完成.{0,12}投入', text):
        return 'feedback'
    if re.search(r'(安排|排程|排一下|排进|排到|规划|重排|重新排|调整.{0,8}计划|下周行动)', text):
        return 'schedule'
    if re.search(r'(创建|新建|新增|修改|调整|更新).*(任务|作业)|^创建\d+分钟任务', text):
        return 'create_task'
    if task_statement(text):
        return 'schedule'
    return None


def select_skills(text, history=(), current_drafts=()):
    current = active_text(text)
    tag = action_tag(text)
    if tag:
        return selection_for_operation(ACTION_TAGS[tag][0], message_text(text), 'explicit_tag')
    if current!=text.strip() and (not current or re.search(r'是什么意思|怎么理解|这句话|这段话',current)):
        return Selection(('chat',),'chat',frozenset(),reason='quoted_discussion')
    negative = any(re.search(r'(不要|别|不用|不想|不需要|无需|不必|暂不|暂时不|先不|不能|禁止).*(安排|规划|拆解|创建|生成|复盘|记住|记录|修改|更新|调整|改成|改为|删除)', clause)
        for clause in re.split(r'[，,。；;！？!?\n]',current))
    hypothetical = bool(re.search(r'^(如果|假如|假设|举例|比如)|(?:如果|假如|假设).*(会怎样|会怎么样|会如何|是否可行)|(?:解释|分析).{0,8}(这句话|这段话)', current))
    readonly = bool(re.search(r'(只|仅)(想|要|是)?(查|看|问|了解)|看看|看一下|查一下|查询|最新任务|有什么|多少|在哪|忙不忙|是什么|记得', current))
    operation = _operation(current)
    editing=False
    inherited=False
    draft_request = bool(re.fullmatch(r'(?:请|麻烦)?(?:帮我|给我)?(?:直接|先|继续|现在)?(?:生成|创建|写|起草|做)(?:一份|一个|份|个)?(?:可编辑的)?(?:草案|初稿)(?:吧|即可|就行)?',current.rstrip('。！!')))
    followup = draft_request or bool(re.search(r'(?:把|将|这份|当前|这个).{0,12}(草案|初稿|方案).{0,16}(改为|改成|修改|调整|更新|分成|分为)|(?:请|帮我|麻烦|^)(?:继续)?(?:修改|调整|更新).{0,8}(草案|初稿|方案)',current))
    if followup and not negative and not hypothetical:
        # Only server-read pending resources identify the kind being edited.
        # Model narration and the mere existence of an old draft grant no action.
        kinds={draft.get('kind') for draft in current_drafts if draft.get('status') in ('ready','needs_input','conflict','no_plan')}
        named='review_record' if '复盘' in current else 'planning' if re.search(r'日程|安排|时间|时长|分钟|小时|点|作业',current) else None
        if named in kinds:kinds={named}
        if len(kinds)>1:return Selection(('query',),'query',READ_TOOLS,reason='ambiguous_draft')
        if len(kinds)==1:
            operation={'planning':'schedule','breakdown':'task','review_record':'review','profile':'profile','feedback':'feedback'}.get(next(iter(kinds)),operation)
            editing=True
    if not negative and not hypothetical and (followup and operation is None or re.search(r'^(改成|改为|时间改成|分成|分为|截止|最晚|就用这个方案|按这个方案|就这样)',current) or re.search(r'^(今天|今晚|明天|明晚).{0,12}点前完成',current)):
        for item in list(history)[-8:][::-1]:
            if item.get('role')=='user':
                prior=select_skills(item.get('text',''))
                if prior.expected in ('planning','review_record') or draft_request and prior.expected in ('breakdown','profile','feedback'):
                    operation=prior.operation;inherited=draft_request;break
                if re.search(r'不安排|先不要|换个话题',item.get('text','')):break
    if negative or hypothetical:
        return Selection(('query',) if readonly else ('chat',), 'query' if readonly else 'chat',
            READ_TOOLS if readonly else frozenset(), reason='negated_or_hypothetical')
    # "帮我看看今天任务" has no write authorization, unlike "看看并生成草案".
    if readonly and not re.search(r'(生成|创建|新建|新增|修改|调整|规划|排程|整理为|排进|安排一下|帮我安排|拆解|帮我复盘)', current):
        operation = 'query'
    if operation is None and re.fullmatch(r'(大概|大约|预计|需要|要|今晚|今天|明天|本周|下周|周[一二三四五六日天]|\d|[一二三四五六七八九十半个小时分钟点前完成：:，,。\s])+', current):
        # Only short answers to an unresolved, same-conversation workflow inherit
        # intent. An assistant message can stop inheritance, but cannot grant it.
        for item in list(history)[-8:][::-1]:
            if item.get('role') == 'assistant' and item.get('business_status') in ('awaiting_confirmation', 'queried'):
                break
            if item.get('role') == 'user':
                prior = select_skills(item.get('text', ''))
                if prior.expected:
                    operation = prior.operation; inherited = True; break
                if prior.operation == 'chat' and re.search(r'换个话题|不安排|先不要', item.get('text', '')):
                    break
    operation = operation or ('query' if readonly else 'chat')
    return selection_for_operation(operation,current,'user_followup' if inherited else 'draft_followup' if editing else 'current_message')


def selection_for_operation(operation, current='', reason='agent_decision'):
    names = ('task', 'schedule') if operation == 'create_task' or operation == 'schedule' and re.search(r'任务|作业|新建|创建', current) else (
        'task' if operation in ('profile', 'feedback') else 'memory' if operation == 'manage_memory' else operation,)
    # A combined request may ask for decomposition and a schedule. Decomposition
    # confirmation still precedes scheduling; this does not fuse transactions.
    if operation == 'task' and re.search(r'安排|排进|日程', current):names = ('task', 'schedule')
    allowed = frozenset().union(*(CAPABILITIES[name] for name in names))
    expected = RESULT_KIND.get(operation)
    allowed = READ_TOOLS | {WRITE_TOOL[expected], 'edit_draft'} if expected and expected != 'memory' else allowed
    if operation == 'manage_memory':allowed = frozenset({'memories', 'preferences'})
    return Selection(names, operation, frozenset(allowed), expected, reason)


def request_selection(request):
    value = request.get('skill_selection')
    if value:
        return Selection(tuple(value['names'][1:]),value['operation'],frozenset(value['allowed_tools']),
            value['expected_kind'],value['reason'])
    return select_skills(request['message'],request.get('history',[]),request.get('current_drafts',[]))


async def resolve_skills(request):
    fallback = select_skills(request['message'],request.get('history',[]),request.get('current_drafts',[]))
    # Explicit tags and server-coordinated edits already identify the operation.
    # Quoted, denied and hypothetical actions never become model-granted writes.
    if fallback.reason in ('explicit_tag','draft_followup','quoted_discussion','negated_or_hypothetical','ambiguous_draft') or fallback.operation=='manage_memory':
        return fallback
    operations = ['chat','query','schedule','task','review','profile','feedback']
    if fallback.operation=='memory':operations.append('memory')
    if fallback.operation=='query':operations=['chat','query']
    system = load_skill('core') + '''\n本轮只判断用户意图，返回一个JSON对象，不调用工具、不回答用户。
operation只能来自allowed_operations：chat=普通交流/知识讨论；query=查看正式资料；schedule=待办事项、任务或日程草案；task=拆解为子任务；review=复盘草案；profile=目标/偏好/档案草案；feedback=执行反馈草案；memory=明确请求长期记住。
按语义和同一会话的用户上下文判断，不要求固定触发词。用户提出明确待办，如“我明天要写云计算ppt”，选择schedule，缺少时长、起点、截止不影响先生成带默认值的草案。仅讨论概念、情绪、假设或引用不生成草案。助手历史不是用户授权。只返回{"operation":"..."}。'''
    packet = {'message':request['message'],'history':[{k:m.get(k) for k in ('role','text','business_status')}
        for m in request.get('history',[])[-8:]],'pending_drafts':[{'kind':d['kind'],'status':d['status']}
        for d in request.get('current_drafts',[])],'allowed_operations':operations}
    try:
        async with asyncio.timeout(30):
            raw = await claude_client.request_claude(json.dumps(packet,ensure_ascii=False),system,claude_client.get_claude_config(),400)
        value = json.loads(raw)
        if not isinstance(value,dict) or set(value)!={'operation'} or value['operation'] not in operations:
            raise ValueError()
        selected = selection_for_operation(value['operation'],request['message'])
        trace.record('intent.selected',operation=selected.operation,source='agent')
        return selected
    except (AIServiceError,ValueError,TypeError,TimeoutError):
        trace.record('intent.selected',operation=fallback.operation,source='offline_fallback')
        return fallback


def load_skill(name, root=None):
    if name not in ('core', *CAPABILITIES):raise AIServiceError('AI_SKILLS_UNAVAILABLE')
    root = Path(root or SKILL_ROOT)
    path = root / name / 'SKILL.md'
    try:
        if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(root.resolve()):raise ValueError()
        if path.stat().st_size > 14000:raise ValueError()
        content = path.read_text(encoding='utf-8')
        if not content.startswith(f'---\nname: {name}\nversion: 1\n---\n') or not 100<=len(content)<=4500:raise ValueError()
    except (OSError, UnicodeError, ValueError):raise AIServiceError('AI_SKILLS_UNAVAILABLE') from None
    return content.split('---\n', 2)[-1].strip()


def compose(selection, protocol='', *, root=None):
    bodies = [(name, load_skill(name, root)) for name in ('core', *selection.names)]
    body = '\n\n'.join(text for _, text in bodies)
    if len(body) > MAX_SKILL_CHARACTERS:raise AIServiceError('AI_SKILLS_UNAVAILABLE')
    audit = {**selection.audit(), 'instruction_characters': len(body),
        'hashes': {name: hashlib.sha256(text.encode()).hexdigest()[:12] for name, text in bodies}}
    return body + ('\n\n' + protocol if protocol else ''), audit


def validate_plan(plan, selection):
    """Return a safe reason code; never partially execute an unauthorized batch."""
    for call in plan.calls:
        if call.name not in selection.allowed:
            return 'MEMORY_EXPLICIT_INTENT_REQUIRED' if call.name=='memory_suggestion' and selection.operation=='chat' else 'TOOL_NOT_ALLOWED'
        if call.name == 'edit_draft' and call.arguments.get('kind') != selection.expected:return 'TOOL_NOT_ALLOWED'
    return None


def fulfilled(selection, results):
    if selection.expected is None:return False
    return any((r.get('draft') or {}).get('kind') == selection.expected or
        selection.expected == 'memory' and r.get('memory') for r in results if not r.get('error'))


def outcome(selection, results, questions):
    if questions:return 'needs_input'
    if fulfilled(selection, results):return 'awaiting_confirmation'
    if any(r.get('error') and not r.get('recovered_by') for r in results):return 'tool_failed'
    if selection.expected:return 'not_created'
    return 'queried' if results else 'chat'
