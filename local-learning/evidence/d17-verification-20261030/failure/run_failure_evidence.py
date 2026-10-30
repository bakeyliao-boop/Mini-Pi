"""D17 failure/window/budget checks; mock models, synthetic input, local files only."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path.cwd()))  # 在 Mini-Pi 项目根目录运行，适配其他设备
from mini_pi.auto_compaction import AutoCompactionSettings
from mini_pi.compaction import generate_summary
from mini_pi.context import ContextProvider, FullHistoryContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input
from mini_pi.loop import run_loop
from mini_pi.message_queue import PendingMessageQueue
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message
from mini_pi.session_store import SessionStore
from mini_pi.summary_call_budget import SummaryCallBudget, SummaryCallBudgetExceeded

ROOT = Path(__file__).parent
HISTORY = [Message('user', '修复登录'), Message('assistant', 'test_login 失败'), Message('user', '继续')]

def setup(summary_response, *, window=None):
    answer = MockProvider([Message('assistant', '模拟回答完成', stop_reason='stop')])
    summary = MockProvider([summary_response])
    answer.max_completion_tokens = summary.max_completion_tokens = 100
    window = window or ContextWindowBudget(10000, 100)
    provider = ContextProvider(answer, FullHistoryContext(), input_estimator=estimate_qwen_input, window_budget=window)
    return answer, summary, window, provider

async def failure(reason, expected_status):
    answer, summary, window, provider = setup(Message('assistant', '部分摘要', stop_reason=reason))
    store = SessionStore(ROOT / f'failure-{reason}.jsonl', f'failure-{reason}')
    result = await run_loop(provider, SimpleNamespace(execute=AsyncMock()), HISTORY, [], session_store=store,
        auto_compaction=AutoCompactionSettings(1, 1), summary_provider=summary, summary_window=window,
        summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1)
    loaded = store.load()
    checks = {'status_matches': result.status == expected_status, 'raw_history_preserved': loaded.history == HISTORY,
              'no_compaction_saved': not any(row['type'] == 'compaction' for row in loaded.records),
              'answer_not_called': not answer.requests, 'one_summary_call': len(summary.requests) == 1,
              'run_end_matches': loaded.records[-1]['data']['status'] == expected_status}
    return {'scenario': f'摘要{reason}', 'status': result.status, 'checks': checks,
            'summary_requests': len(summary.requests), 'answer_requests': len(answer.requests),
            'summary_usage': None, 'answer_usage': None, 'session_file': store.path.name}

async def final_window():
    queue = PendingMessageQueue()
    def summarized(_items, _tools):
        queue.enqueue('新要求：' + 'x' * 5000)
        return Message('assistant', '登录问题摘要', stop_reason='stop')
    answer, summary, window, provider = setup(summarized, window=ContextWindowBudget(1000, 100))
    store = SessionStore(ROOT / 'window-after-new-steering.jsonl', 'window-after-steering')
    result = await run_loop(provider, SimpleNamespace(execute=AsyncMock()), HISTORY, [], session_store=store,
        auto_compaction=AutoCompactionSettings(1, 1), summary_provider=summary, summary_window=ContextWindowBudget(10000, 100),
        summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1, get_steering_messages=queue.drain_one)
    loaded = store.load()
    checks = {'budget_exhausted': result.status == 'budget_exhausted', 'answer_not_called': not answer.requests,
              'summary_saved': sum(row['type'] == 'compaction' for row in loaded.records) == 1,
              'raw_history_preserved': loaded.history[:len(HISTORY)] == HISTORY,
              'new_steering_saved': len(loaded.history) == len(HISTORY) + 1 and loaded.history[-1].content.startswith('新要求：')}
    return {'scenario': '新增 steering 后完整回答请求超出窗口', 'status': result.status,
            'window_tokens': window.context_window_tokens, 'reserved_output_tokens': window.reserved_output_tokens,
            'checks': checks, 'summary_requests': len(summary.requests), 'answer_requests': len(answer.requests),
            'summary_usage': None, 'answer_usage': None, 'session_file': store.path.name}

async def separate_budget():
    answer, summary, window, provider = setup(Message('assistant', '登录问题摘要', stop_reason='stop'))
    store = SessionStore(ROOT / 'budget-separate.jsonl', 'budget-separate')
    result = await run_loop(provider, SimpleNamespace(execute=AsyncMock()), HISTORY, [], session_store=store,
        max_model_turns=1, auto_compaction=AutoCompactionSettings(1, 1), summary_provider=summary,
        summary_window=window, summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1)
    checks = {'finished': result.status == 'finished', 'one_summary_call': len(summary.requests) == 1,
              'one_answer_call': len(answer.requests) == 1}
    return {'scenario': 'max_model_turns 为 1 的调用口径', 'status': result.status, 'max_model_turns': 1,
            'summary_requests': len(summary.requests), 'answer_requests': len(answer.requests), 'checks': checks,
            'summary_usage': None, 'answer_usage': None, 'session_file': store.path.name}

async def summary_cap():
    _, summary, window, _ = setup(Message('assistant', '登录问题摘要', stop_reason='stop'))
    budget = SummaryCallBudget(1)
    await generate_summary(HISTORY, summary, estimate_qwen_input, window, budget)
    blocked = False
    try:
        await generate_summary(HISTORY, summary, estimate_qwen_input, window, budget)
    except SummaryCallBudgetExceeded:
        blocked = True
    return {'scenario': '摘要调用上限阻止第二次', 'checks': {'second_call_blocked': blocked,
            'one_actual_call': len(summary.requests) == 1, 'one_budget_used': budget.used_calls == 1},
            'summary_requests': len(summary.requests), 'summary_usage': None}

async def main():
    for name in ('failure-length.jsonl', 'failure-error.jsonl', 'failure-aborted.jsonl', 'window-after-new-steering.jsonl', 'budget-separate.jsonl', 'failure-results.json'):
        if (ROOT / name).exists():
            raise RuntimeError(f'证据文件已存在，拒绝覆盖: {name}')
    scenarios = [await failure('length', 'error'), await failure('error', 'error'), await failure('aborted', 'cancelled'),
                 await final_window(), await separate_budget(), await summary_cap()]
    results = {'model': 'MockProvider（预设响应，不调用真实模型）', 'usage_explanation': '模型服务未调用，usage 不可用（null，不代表零）',
               'scenarios': scenarios, 'all_passed': all(all(s['checks'].values()) for s in scenarios)}
    (ROOT / 'failure-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if not results['all_passed']:
        raise SystemExit(1)

asyncio.run(main())
