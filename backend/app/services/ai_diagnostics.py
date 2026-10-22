"""Bounded metadata only. Never record text, inputs, URLs, headers or secrets."""
from contextvars import ContextVar
import logging
import re

_sink = ContextVar('ai_diagnostics', default=None)
logger = logging.getLogger(__name__)
FIELDS = frozenset('calls arguments name questions continue_after_read actions fields title duration_minutes deadline priority profile kind id version content schedule day start_time segments break_minutes text scope start end task_id'.split())


def begin(run_id, attempt):
    return _sink.set({'run_id':run_id,'attempt':attempt,'events':[]})


def record(stage, **metadata):
    sink=_sink.get()
    if sink is None or len(sink['events'])>=64:return
    # Callers provide only allowlisted metadata, never an exception string/body.
    event={'stage':stage,**metadata}
    sink['events'].append(event)
    logger.info('ai_trace %s',{'run_id':sink['run_id'],'attempt':sink['attempt'],**event})


def schema_errors(exc):
    return [{'path':[part if type(part) is int or part in FIELDS else 'unknown_field' for part in e['loc']],
        'type':e['type'] if re.fullmatch(r'[a-z_]+',e['type']) else 'validation_error'}
        for e in exc.errors(include_input=False,include_url=False)[:8]]


def snapshot():
    value=_sink.get()
    return {'version':1,**value} if value else None


def end(token):
    _sink.reset(token)
