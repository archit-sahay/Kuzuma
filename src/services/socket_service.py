import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from src.utils.prompt_template import prompt
from src.config.socket_config import create_socketio_app
from src.utils.tool_description_list import tools
from src.utils.tool_utils import tool_map
from src.utils.cache import cache
from src.repository.history_repository import add_history
from src.config.db_config import get_db
from src.services.llm_service import llm, summary_client, SUMMARY_MODEL
from src.logger import get_logger

log = get_logger(__name__)

# Strip leaked function call tags from LLM responses
_FUNC_TAG_RE = re.compile(r'<function=\w+>.*?</function>', re.DOTALL)

def _sanitize_response(content: str) -> str:
    """Remove raw function call tags that some models leak into text."""
    return _FUNC_TAG_RE.sub('', content).strip()

TOOL_TIMEOUT = 15  # seconds
MAX_HISTORY = 20  # messages before compaction
KEEP_RECENT = 10  # messages to keep after compaction
SESSION_TTL = 1800  # 30 minutes idle timeout

sio = create_socketio_app()
message_histories = {}
user_map = {}
session_last_active = {}  # sid -> timestamp


# ─── Session Cleanup ─────────────────────────────────────────────────────────

async def cleanup_stale_sessions():
    """Background task: evict sessions idle for more than SESSION_TTL seconds."""
    while True:
        await asyncio.sleep(600)  # run every 10 minutes
        now = time.time()
        stale = [sid for sid, ts in session_last_active.items() if now - ts > SESSION_TTL]
        for sid in stale:
            log.info(f"Evicting stale session: {sid}")
            message_histories.pop(sid, None)
            user_map.pop(sid, None)
            session_last_active.pop(sid, None)
        # Clean up expired cache entries
        cache.cleanup()


# ─── History Compaction ───────────────────────────────────────────────────────

async def _compact_history(sid):
    """Summarize older messages to save tokens while preserving context."""
    history = message_histories.get(sid, [])
    if len(history) <= MAX_HISTORY:
        return

    # Split: system prompt(s) + old messages + recent messages
    system_msgs = [m for m in history if m["role"] == "system"]
    non_system = [m for m in history if m["role"] != "system"]
    old_msgs = non_system[:-KEEP_RECENT]
    recent_msgs = non_system[-KEEP_RECENT:]

    # Build text to summarize
    summary_lines = []
    for m in old_msgs:
        role = m.get("role", "unknown")
        content = m.get("content", "")[:200]  # truncate long entries
        if role == "function":
            summary_lines.append(f"[Tool {m.get('name', '?')}]: {content}")
        else:
            summary_lines.append(f"{role}: {content}")

    summary_text = "\n".join(summary_lines)

    try:
        summary_response = await asyncio.wait_for(
            asyncio.to_thread(
                summary_client.chat.completions.create,
                messages=[{
                    "role": "user",
                    "content": f"Summarize this conversation in 2-3 sentences. Preserve key facts, user questions, and what was discussed:\n\n{summary_text}"
                }],
                model=SUMMARY_MODEL,
                temperature=0.3,
                max_tokens=150
            ),
            timeout=10
        )
        summary = summary_response.choices[0].message.content
        log.info(f"Compacted {len(old_msgs)} messages into summary for {sid}")
    except Exception as e:
        log.warning(f"History compaction failed, trimming instead: {e}")
        summary = "Earlier in this conversation, the user asked about Archit's background and interests."

    # Rebuild history: system + summary + recent
    message_histories[sid] = system_msgs + [
        {"role": "system", "content": f"Previous conversation summary: {summary}"}
    ] + recent_msgs


# ─── LLM Call Wrapper ─────────────────────────────────────────────────────────

async def _llm_call(messages, use_tools=True, temperature=0.7):
    """Call LLM through fallback chain (Groq → OpenRouter)."""
    return await llm.create(
        messages=messages,
        tools=tools if use_tools else None,
        tool_choice="auto" if use_tools else None,
        temperature=temperature,
    )


async def _iterate_stream(stream):
    """Iterate over a sync streaming response, yielding chunks via a queue."""
    queue = asyncio.Queue()

    def _reader():
        try:
            for chunk in stream:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    queue.put_nowait(delta.content)
        finally:
            queue.put_nowait(None)  # sentinel

    # Run the sync reader in a thread
    asyncio.get_event_loop().run_in_executor(None, _reader)

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item


# ─── Tool Execution ──────────────────────────────────────────────────────────

async def _execute_tool(tool_name, tool_args):
    """Execute a tool with timeout and error handling."""
    if tool_name not in tool_map:
        log.warning(f"Unknown tool requested: {tool_name}")
        return {"error": f"Unknown tool: {tool_name}", "status": "error"}

    tool_fn = tool_map[tool_name]
    if not tool_args:
        tool_args = {}
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(tool_fn, **tool_args),
            timeout=TOOL_TIMEOUT
        )
        log.info(f"[{tool_name}] result: {result}")
        return {"result": result, "status": "success"}
    except asyncio.TimeoutError:
        log.error(f"[{tool_name}] timed out after {TOOL_TIMEOUT}s")
        return {"error": f"{tool_name} timed out", "status": "error"}
    except Exception as e:
        log.error(f"[{tool_name}] failed: {e}")
        return {"error": str(e), "status": "error"}


# ─── Core Services ────────────────────────────────────────────────────────────

async def start_service(sid, data):
    if sid not in user_map:
        log.info(f"Start Data: {data}")
        user_map[sid] = data
    session_last_active[sid] = time.time()
    await sio.emit("message", {
        "text": "Hey! I'm Archit — or well, a digital version of me. Ask me anything about my work, projects, or my questionable anime taste. What's up?"
    }, to=sid)


async def message_service(sid, message: str):
    session_last_active[sid] = time.time()

    # Initialize history for new sessions
    if sid not in message_histories:
        message_histories[sid] = [{"role": "system", "content": prompt}]

    # Add the user's message
    message_histories[sid].append({"role": "user", "content": message})

    # Compact history if needed
    await _compact_history(sid)

    try:
        # Thinking indicator before LLM call
        await sio.emit("typing", {"text": "Thinking..."}, to=sid)

        # First LLM call
        response = await _llm_call(message_histories[sid])
        response_message = response.choices[0].message

        # Handle tool calls (max 3 rounds to prevent infinite loops)
        tool_rounds = 0
        while hasattr(response_message, "tool_calls") and response_message.tool_calls and tool_rounds < 3:
            tool_rounds += 1
            log.info(f"Tool round {tool_rounds}: {len(response_message.tool_calls)} call(s)")

            # Add the assistant's tool-call message to history FIRST
            message_histories[sid].append({
                "role": "assistant",
                "content": response_message.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in response_message.tool_calls
                ]
            })

            # Parse all tool calls first, emit typing for all
            parsed_calls = []
            tool_names = []
            for tool_call in response_message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments) or {}
                except (json.JSONDecodeError, TypeError):
                    log.error(f"[{tool_name}] bad arguments: {tool_call.function.arguments}")
                    message_histories[sid].append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": f"Invalid JSON arguments for {tool_name}. Please retry with valid JSON.", "status": "error"})
                    })
                    continue
                parsed_calls.append((tool_call, tool_name, tool_args))
                tool_names.append(tool_name.replace('_', ' '))

            if parsed_calls:
                # Show what we're checking
                await sio.emit("typing", {"text": f"Checking {', '.join(tool_names)}..."}, to=sid)

                # Execute all tools in parallel
                tasks = [_execute_tool(name, args) for _, name, args in parsed_calls]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for (tool_call, tool_name, _), result in zip(parsed_calls, results):
                    if isinstance(result, Exception):
                        log.error(f"[{tool_name}] gather exception: {result}")
                        result = {"error": str(result), "status": "error"}
                    message_histories[sid].append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result)
                    })

            # Call LLM again with tool results
            await sio.emit("typing", {"text": "Thinking..."}, to=sid)
            response = await _llm_call(message_histories[sid])
            response_message = response.choices[0].message

        # If we already have a non-streamed response (from tool loop), use it
        if response_message.content:
            content = _sanitize_response(response_message.content)
            message_histories[sid].append({"role": "assistant", "content": content})
            log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Emitting Response: [{content[:100]}...]")
            await sio.emit("message", {"text": content}, to=sid)
        else:
            # Stream the final response for perceived speed
            try:
                stream = await llm.create(
                    messages=message_histories[sid],
                    tools=None,  # no tools for final response
                    temperature=0.7,
                    stream=True,
                )
                full_content = ""
                async for chunk_wrapper in _iterate_stream(stream):
                    delta = chunk_wrapper
                    if delta:
                        full_content += delta
                        await sio.emit("stream", {"text": delta}, to=sid)

                content = full_content or "I got a bit lost there. Could you rephrase that?"
                message_histories[sid].append({"role": "assistant", "content": content})
                await sio.emit("stream_end", {}, to=sid)
                log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Streamed Response: [{content[:100]}...]")
            except Exception as stream_err:
                log.warning(f"Streaming failed, falling back: {stream_err}")
                content = "I got a bit lost there. Could you rephrase that?"
                message_histories[sid].append({"role": "assistant", "content": content})
                await sio.emit("message", {"text": content}, to=sid)

    except asyncio.TimeoutError:
        log.error(f"LLM call timed out for {sid}")
        await sio.emit("message", {
            "text": "That's taking longer than expected — my brain needs a moment. Try again?"
        }, to=sid)
    except Exception as e:
        log.error(f"Exception in message_service: {e}", exc_info=True)
        await sio.emit("message", {
            "text": "Something tripped me up. Mind trying that again?"
        }, to=sid)


async def disconnect_service(sid):
    try:
        if sid not in message_histories or sid not in user_map:
            log.info(f"No data found for sid: {sid}")
            return

        user_data = user_map[sid]
        if isinstance(user_data, str):
            user_data = json.loads(user_data)
        name = user_data.get("name", "Unknown User")
        email = user_data.get("email", "unknown@unknown")

        history = message_histories[sid]

        # Build structured messages list (skip system prompts)
        structured_messages = []
        for entry in history:
            role = entry.get("role")
            if role == "system":
                continue
            structured_messages.append({
                "role": role,
                "content": entry.get("content", ""),
                "timestamp": datetime.now().isoformat()
            })

        # Retry with fallback to local file
        saved = False
        for attempt in range(2):
            try:
                async with get_db() as db:
                    await add_history(db=db, name=name, email=email, messages=structured_messages)
                saved = True
                break
            except Exception as db_err:
                if attempt == 0:
                    log.warning(f"MongoDB save attempt 1 failed, retrying: {db_err}")
                    await asyncio.sleep(1)
                else:
                    log.error(f"MongoDB save failed after 2 attempts: {db_err}")

        if not saved:
            # Write to local fallback file
            try:
                fallback = {
                    "name": name, "email": email,
                    "messages": structured_messages,
                    "timestamp": datetime.now().isoformat()
                }
                fallback_path = Path("logs/failed_saves.jsonl")
                fallback_path.parent.mkdir(parents=True, exist_ok=True)
                with open(fallback_path, "a") as f:
                    f.write(json.dumps(fallback) + "\n")
                log.info(f"Wrote fallback history for {email} to {fallback_path}")
            except Exception as file_err:
                log.error(f"Fallback file write also failed: {file_err}")

    except Exception as e:
        log.error(f"Error in disconnect_service: {e}", exc_info=True)
    finally:
        # Always clean up memory
        message_histories.pop(sid, None)
        user_map.pop(sid, None)
        session_last_active.pop(sid, None)
