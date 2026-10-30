"""D17 成功流程证据：仅使用预设响应、合成历史与本地会话。"""
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path.cwd()))  # 在 Mini-Pi 项目根目录运行，适配其他设备
from mini_pi.auto_compaction import AutoCompactionSettings
from mini_pi.context import ContextProvider, FullHistoryContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input
from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message
from mini_pi.session_store import SessionStore

OUT = Path(__file__).parent


async def main():
    path = OUT / "normal-session.jsonl"
    if path.exists():
        raise FileExistsError("为保留证据，不覆盖已有会话；使用新的证据目录。")
    history = [
        Message("user", "目标：修复登录。约束：不要修改验收测试。"),
        Message("assistant", "已修改 auth.py；test_login 失败；待办：检查数据库。"),
        Message("user", "继续"),
    ]
    scripted_summary = "目标：修复登录；约束：不要修改验收测试；已修改 auth.py；test_login 失败；待办：检查数据库。"
    summary = MockProvider([Message("assistant", scripted_summary, stop_reason="stop")])
    answer = MockProvider([Message("assistant", "继续检查数据库。", stop_reason="stop")])
    summary.max_completion_tokens = answer.max_completion_tokens = 1000
    window = ContextWindowBudget(10000, 1000, 100)
    provider = ContextProvider(answer, FullHistoryContext(), input_estimator=estimate_qwen_input, window_budget=window)
    store = SessionStore(path, "d17-normal")
    result = await run_loop(
        provider, SimpleNamespace(execute=AsyncMock()), history, [], session_store=store,
        max_model_turns=1, total_timeout_seconds=30,
        auto_compaction=AutoCompactionSettings(1, 1), summary_provider=summary,
        summary_window=window, summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1,
    )
    loaded = store.load()
    compactions = [r for r in loaded.records if r["type"] == "compaction"]
    assert result.status == "finished", result.error
    assert len(summary.requests) == len(answer.requests) == len(compactions) == 1
    assert loaded.history[:len(history)] == history
    assert compactions[0]["data"]["summary"] == scripted_summary
    summary_input = "\n".join(m.content for m in summary.requests[0] if isinstance(m, Message))
    answer_input = "\n".join(m.content for m in answer.requests[0] if isinstance(m, Message))
    for fact in ("修复登录", "不要修改验收测试", "auth.py", "test_login", "检查数据库"):
        assert fact in summary_input, ("摘要请求缺少", fact)
        assert fact in answer_input, ("回答请求缺少", fact)
    estimate = estimate_qwen_input(answer.requests[0], [])
    assert estimate.estimated_input_tokens + window.reserved_output_tokens + window.safety_margin_tokens <= window.context_window_tokens
    evidence = {
        "scenario": "成功：预设模拟摘要与回答，合成数据，未调用真实模型或工具",
        "status": result.status,
        "task_passed": result.task_passed,
        "original_history": [asdict(m) for m in history],
        "session_history_after_run": [asdict(m) for m in loaded.history],
        "original_history_preserved": loaded.history[:len(history)] == history,
        "compaction_record": compactions[0],
        "summary_model_request": [asdict(m) for m in summary.requests[0]],
        "summary_model_response_preset": scripted_summary,
        "answer_model_request": [asdict(m) for m in answer.requests[0]],
        "answer_model_response_preset": "继续检查数据库。",
        "budget": {
            "max_model_turns_answer_rounds": 1,
            "summary_call_limit": 1,
            "summary_calls_observed": len(summary.requests),
            "answer_calls_observed": len(answer.requests),
            "total_timeout_seconds": 30,
            "auto_compaction_trigger_tokens": 1,
            "keep_recent_tokens": 1,
            "answer_window": asdict(window),
            "answer_request_estimate": asdict(estimate),
            "provider_usage": None,
            "provider_usage_reason": "模拟模型未返回 usage；未知，不视为零",
        },
    }
    (OUT / "normal-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "normal-readme.md").write_text(
        "# D17 成功场景：模拟模型\n\n"
        "任务、修改文件和测试状态均为合成样例；摘要及回答均为预设响应，未调用真实模型或执行工具。\n\n"
        "本次实际执行：触发摘要 → 保存摘要 → 生成回答请求 → 返回模拟回答。原始历史已保留。\n\n"
        f"摘要调用 {len(summary.requests)} 次，回答调用 {len(answer.requests)} 次；回答轮数上限 1，摘要独立上限 1，总时限 30 秒。\n\n"
        f"回答输入估算 {estimate.estimated_input_tokens} tokens，输出预留 {window.reserved_output_tokens}，安全余量 {window.safety_margin_tokens}，窗口 {window.context_window_tokens}。估算不是服务端 usage。\n\n"
        "`normal-session.jsonl` 是会话原始记录；`normal-evidence.json` 包含完整输入、摘要、模型请求和预算。模拟模型没有 usage，实际消耗为未知，不能据此证明真实模型的摘要质量。\n",
        encoding="utf-8",
    )
    print(f"PASS normal status={result.status}; summary_calls={len(summary.requests)}; answer_calls={len(answer.requests)}; input_estimate={estimate.estimated_input_tokens}")
    print(f"Evidence: {OUT}")


asyncio.run(main())
