"""Product skills: trusted local instructions, deterministic routing, code-owned policy.

No credentials, database access or model calls. Text/history never grant a new
tool capability. The router is deliberately conservative rather than a semantic
classifier; a false negative can be retried but must not create business facts.
"""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .claude_client import AIServiceError

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
    return None


def select_skills(text, history=()):
    current = active_text(text)
    if current!=text.strip() and (not current or re.search(r'是什么意思|怎么理解|这句话|这段话',current)):
        return Selection(('chat',),'chat',frozenset(),reason='quoted_discussion')
    negative = any(re.search(r'(不要|别|不用|不想|不需要|无需|不必|暂不|暂时不|先不|不能|禁止).*(安排|规划|拆解|创建|生成|复盘|记住|记录|修改|删除)', clause)
        for clause in re.split(r'[，,。；;！？!?\n]',current))
    hypothetical = bool(re.search(r'^(如果|假如|假设|举例|比如)|(?:如果|假如|假设).*(会怎样|会怎么样|会如何|是否可行)|(?:解释|分析).{0,8}(这句话|这段话)', current))
    readonly = bool(re.search(r'(只|仅)(想|要|是)?(查|看|问|了解)|看看|看一下|查一下|查询|最新任务|有什么|多少|在哪|忙不忙|是什么|记得', current))
    operation = _operation(current)
    if negative or hypothetical:
        return Selection(('query',) if readonly else ('chat',), 'query' if readonly else 'chat',
            READ_TOOLS if readonly else frozenset(), reason='negated_or_hypothetical')
    # "帮我看看今天任务" has no write authorization, unlike "看看并生成草案".
    if readonly and not re.search(r'(生成|创建|新建|新增|修改|调整|规划|排程|整理为|排进|安排一下|帮我安排|拆解|帮我复盘)', current):
        operation = 'query'
    inherited = False
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
    names = ('task', 'schedule') if operation == 'create_task' or operation == 'schedule' and re.search(r'任务|作业|新建|创建', current) else (
        'task' if operation in ('profile', 'feedback') else 'memory' if operation == 'manage_memory' else operation,)
    # A combined request may ask for decomposition and a schedule. Decomposition
    # confirmation still precedes scheduling; this does not fuse transactions.
    if operation == 'task' and re.search(r'安排|排进|日程', current):names = ('task', 'schedule')
    allowed = frozenset().union(*(CAPABILITIES[name] for name in names))
    expected = RESULT_KIND.get(operation)
    allowed = READ_TOOLS | {WRITE_TOOL[expected], 'edit_draft'} if expected and expected != 'memory' else allowed
    if operation == 'manage_memory':allowed = frozenset({'memories', 'preferences'})
    return Selection(names, operation, frozenset(allowed), expected, 'user_followup' if inherited else 'current_message')


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
    if any(r.get('error') for r in results):return 'tool_failed'
    if fulfilled(selection, results):return 'awaiting_confirmation'
    if selection.expected:return 'not_created'
    return 'queried' if results else 'chat'
