"""Trusted, bounded defaults from user messages only; no model output or I/O.

Precedence: current user > earlier user > confirmed preference > defaults.
The parser deliberately covers common Chinese expressions, not arbitrary prose.
"""
import re
from datetime import date, datetime, time, timedelta
from ..workspace_schemas import SchedulePreview, DRAFT_DEFAULTS
from .assistant_clock import SHANGHAI

DEFAULTS = DRAFT_DEFAULTS
STARTS = {'早上': '09:00', '上午': '09:00', '中午': '12:00', '下午': '14:00',
    '晚上': '19:00', '今晚': '19:00', '明晚': '19:00', '后晚': '19:00'}
NUMBER = r'(?:\d+(?:\.\d+)?|[零一二两三四五六七八九十百]+)'
DAY_TEXT = r'(?:20\d{2}-\d{2}-\d{2}|(?:20\d{2}年)?\d{1,2}月\d{1,2}[日号]|大后天|后天|后晚|明天|明晚|今天|今晚|次日|第二天|(?:下周|本周|这周|周|星期)[一二三四五六日天])'
PERIOD_TEXT = r'(?:早上|上午|中午|下午|晚上|今晚|明晚|后晚)'
CLOCK_TEXT = NUMBER + r'(?:点|[:：])(?:半|' + NUMBER + r'(?:分)?)?'


def number(text):
    if re.fullmatch(r'\d+(?:\.\d+)?', text):return float(text)
    digits = dict(zip('零一二三四五六七八九', range(10)));digits['两'] = 2
    if text == '十':return 10
    if '十' in text:
        a, b = text.split('十', 1)
        return digits.get(a, 1)*10 + digits.get(b, 0)
    return digits.get(text)


def duration(text):
    text = re.sub(r'(休息|每段)\s*'+NUMBER+r'\s*分钟', '', text)
    match = re.search('('+NUMBER+r')(?:个)?半小时', text)
    if match and number(match[1]) is not None:return int((number(match[1])+.5)*60)
    if '半小时' in text:return 30
    match = re.search('('+NUMBER+r')\s*(?:个)?小时(?:\s*('+NUMBER+r')\s*分钟)?', text)
    if match and number(match[1]) is not None:return int(number(match[1])*60+(number(match[2]) if match[2] else 0))
    match = re.search('('+NUMBER+r')\s*分钟', text)
    if match and number(match[1]) is not None:return int(number(match[1]))


def clock(text):
    match = re.search(r'(?:(早上|上午|中午|下午|晚上|今晚|明晚|后晚)\s*)?('+NUMBER+r')(?:点|[:：])(?:(半)|('+NUMBER+r')(?:分)?)?', text)
    if not match:return None
    hour = number(match[2]);minute = 30 if match[3] else number(match[4]) if match[4] else 0
    if hour is None or minute is None:return None
    if match[1] in ('下午','晚上','今晚','明晚','后晚') and hour<12:hour+=12
    if 0<=hour<24 and 0<=minute<60:return f'{int(hour):02}:{int(minute):02}'


def day(text, now, *, next_day_from=None):
    match = re.search(DAY_TEXT, text)
    if not match:return None
    value=match[0]
    if re.fullmatch(r'20\d{2}-\d{2}-\d{2}',value):return date.fromisoformat(value)
    explicit=re.fullmatch(r'(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})[日号]',value)
    if explicit:return date(int(explicit[1] or now.year),int(explicit[2]),int(explicit[3]))
    if value in ('次日','第二天'):return (next_day_from or now.date())+timedelta(days=1)
    relative={'今天':0,'今晚':0,'明天':1,'明晚':1,'后天':2,'后晚':2,'大后天':3}
    if value in relative:return now.date()+timedelta(days=relative[value])
    index='一二三四五六日'.find(value[-1].replace('天','日'))
    return now.date()-timedelta(days=now.weekday())+timedelta(days=index+(7 if value.startswith('下周') else 0))


def period_start(text):
    matches=list(re.finditer(PERIOD_TEXT,text))
    return STARTS[matches[-1][0]] if matches else None


def deadline_clause(text):
    """Keep execution and deadline dates/periods in separate scopes."""
    match=re.search(r'(?:截止(?:日期|时间)?(?:是|到|为|在)?|截至|DDL[：: ]*|最晚)([^，,。；;\n#＃]{1,80})',text,re.I)
    if match and match[1].strip():return text[:match.start()]+text[match.end():],match[1]
    temporal=rf'(?:{DAY_TEXT})?\s*(?:{PERIOD_TEXT})?\s*{CLOCK_TEXT}|(?:{DAY_TEXT})?\s*{PERIOD_TEXT}'
    match=re.search(rf'({temporal})\s*(?:(?:之前|前)(?:完成|提交|交|截止)?|截止)',text)
    if match:return text[:match.start()]+text[match.end():],match[1]
    return text,None


def user_values(text, now, *, schedule_day=None):
    # Instructions inside quotations/code do not authorize a fallback. Routing
    # is checked separately; here preserve a quoted task name as data.
    text = re.sub(r'```[\s\S]*?```|`[^`]*`', '', text)[:2000]
    values = {}
    minutes = duration(text)
    if minutes is not None:values['duration_minutes'] = minutes
    priority=re.search(r'优先级(?:设为|是|改成|为)?(高|普通|正常|低)',text)
    if priority:values['priority']={'高':'high','普通':'normal','正常':'normal','低':'low'}[priority[1]]
    execution,deadline=deadline_clause(text)
    execution_day=day(execution,now)
    if execution_day:values['day']=execution_day.isoformat()
    start=period_start(execution)
    if start:values['start_time']=start;values['start_exact']=False
    at=clock(execution)
    if at:values['start_time']=at;values['start_exact']=True
    if deadline is not None:
        at=clock(deadline) or period_start(deadline)
        if at:
            end_day=day(deadline,now,next_day_from=execution_day or schedule_day) or execution_day or schedule_day or now.date()
            values['deadline']=datetime.combine(end_day,time.fromisoformat(at),SHANGHAI).isoformat()
    title_text = re.split(r'[，,。；;\n]',execution.strip('，,。；;\n '))[0]
    title_text = re.sub(r'20\d{2}-\d{2}-\d{2}|'+NUMBER+r'(?:个)?半?小时|半小时|'+NUMBER+r'分钟', '',title_text)
    title_text = re.sub(r'(?:早上|上午|中午|下午|晚上|今晚|明晚)?'+NUMBER+r'(?:点|[:：])(?:半|'+NUMBER+r'分?)?', '',title_text)
    # A colon after the task name introduces details, not a replacement name.
    title_text = re.sub(r'^(?:任务名称|任务|名称|标题)[：:]\s*','',title_text)
    title_text = re.sub(r'^(?:'+DAY_TEXT+r'|我|请|你|帮我|早上|晚上|上午|中午|下午|想要|打算|准备|计划|要|有个|有一个|需要|完成|写|制作|安排一下|安排|排一下|排|创建|新建|把|将|给我|做|一下|\s|：|:)+', '',title_text)
    match = re.search(r'([\u4e00-\u9fffA-Za-z0-9 ]{0,60}(?:作业|报告|实验|论文|考试|复习|项目|阅读|PPT|演示文稿|幻灯片))',title_text,re.I)
    if match:values['title'] = match[1].strip(' “”“')
    segment = re.search(r'(?:分成|分为)('+NUMBER+r')段',text)
    if segment and number(segment[1]) is not None:values['segments'] = int(number(segment[1]))
    each = re.search(r'每段('+NUMBER+r')分钟',text)
    if each and 'segments' in values:values['duration_minutes'] = int(number(each[1])*values['segments'])
    rest = re.search(r'休息('+NUMBER+r')分钟',text)
    if rest and number(rest[1]) is not None:values['break_minutes'] = int(number(rest[1]))
    return values


def schedule(request, now, *, base=None, sources=None, preferences=None):
    values = {**DEFAULTS, 'day': now.date().isoformat(), **(base or {})}
    origins = {key:'system_default' for key in values}
    origins.update(sources or {})
    # Only actual confirmed settings supplied by the caller. Sample preferences
    # never get labelled as a user decision.
    windows = (preferences or {}).get('task_windows',{}).get('*',[])
    history = [] if base else [m['text'] for m in request.get('history',[]) if m.get('role')=='user'][-8:]
    for text in history:
        parsed=user_values(text,now,schedule_day=date.fromisoformat(str(values['day'])))
        for key,value in parsed.items():
            values[key]=value;origins[key]='system_default' if key=='start_time' and not parsed.get('start_exact') else 'conversation_context'
    parsed=user_values(request['message'],now,schedule_day=date.fromisoformat(str(values['day'])))
    if base and parsed.get('start_exact') and int(parsed['start_time'][:2])<12 and int(base['start_time'][:2])>=12 and not re.search(r'早上|上午|中午|凌晨|下午|晚上|今晚|明晚',request['message']):
        parsed['start_time']=f"{int(parsed['start_time'][:2])+12:02}"+parsed['start_time'][2:]
    for key,value in parsed.items():
        values[key]=value;origins[key]='system_default' if key=='start_time' and not parsed.get('start_exact') else 'user_explicit'
    if not base and origins['start_time']=='system_default':
        weekday=datetime.fromisoformat(str(values['day'])).isoweekday()
        applicable=[w for w in windows if (not w.get('weekdays') or weekday in w['weekdays']) and w['start']>=values['start_time']]
        if applicable:values['start_time']=applicable[0]['start'];origins['start_time']='confirmed_preference'
    if values['title']=='待命名任务':origins['title']='unresolved'
    if not values.get('deadline'):origins['deadline']='unresolved'
    return SchedulePreview.model_validate(values), origins


def review_range(text, now):
    day=now.date()
    if '今天' in text:return day,day+timedelta(days=1),'day'
    if '昨天' in text:return day-timedelta(days=1),day,'day'
    if '本月' in text or '这个月' in text:
        start=day.replace(day=1);end=(start+timedelta(days=32)).replace(day=1)
        return start,end,'month'
    start=day-timedelta(days=day.weekday())
    return start,start+timedelta(days=7),'week'


def calendar_range(text, now):
    if any(word in text for word in ('本周','这周','下周')):
        start=now.date()-timedelta(days=now.weekday())+timedelta(days=7 if '下周' in text else 0)
        return start,start+timedelta(days=7)
    start=datetime.fromisoformat(user_values(text,now).get('day',now.date().isoformat())).date()
    return start,start+timedelta(days=1)
