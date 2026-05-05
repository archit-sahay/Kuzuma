import asyncio
import json
import os
import random
import re
import time
import uuid
import requests as http_requests
from datetime import datetime, timezone
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
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
MAX_HISTORY = 20  # messages before compaction
KEEP_RECENT = 10  # messages to keep after compaction
SESSION_TTL = 1800  # 30 minutes idle timeout

sio = create_socketio_app()
message_histories = {}
save_histories = {}  # sid -> list of {role, content, timestamp} — never compacted, for MongoDB + Discord
save_tool_calls = {}  # sid -> list of {name, args, timestamp} — tool calls log for MongoDB
user_map = {}
session_last_active = {}  # sid -> timestamp
session_ips = {}  # sid -> client IP captured at connect


# ─── Canned fallback replies ─────────────────────────────────────────────────
# When the LLM chain fails or times out we still want to say *something*.
# Multiple variants per category so a visitor retrying twice doesn't see the
# identical line twice in a row.

_CANNED_REPLIES = {
    "generic_error": [
        "Something tripped me up. Mind trying that again?",
        "Brain freeze — give me another shot?",
        "My circuits hiccupped. Try me again?",
        "That one didn't compile. Retry?",
        "Yeah no, that broke me. One more time?",
        "404 on my brain. Send it once more?",
    ],
    "timeout": [
        "That's taking longer than expected — my brain needs a moment. Try again?",
        "Took too long to think on that one. Try again?",
        "I zoned out mid-thought. Repeat that?",
        "Brain went on a coffee break. Try once more?",
    ],
    "stream_fallback": [
        "I got a bit lost there. Could you rephrase that?",
        "Lost the plot. Mind rephrasing?",
        "Drew a blank. Wanna try a different angle?",
        "That one slipped through. Say it again?",
    ],
}


async def _emit_and_save_canned(sid, category):
    """Emit a randomly-picked canned reply AND record it as the assistant
    turn so the saved transcript matches what the visitor actually saw."""
    text = random.choice(_CANNED_REPLIES[category])
    message_histories.setdefault(sid, []).append({"role": "assistant", "content": text})
    save_histories.setdefault(sid, []).append({
        "role": "assistant", "content": text,
        "timestamp": datetime.now().isoformat()
    })
    await sio.emit("message", {"text": text}, to=sid)
    return text


# ─── Discord Notification ────────────────────────────────────────────────────

async def _notify_discord(name: str, email: str, save_messages: list, conversation_id: str = None, reason: str = "disconnect", client_ip: str = None):
    """Send a chat summary to Discord webhook on conversation end."""
    if not DISCORD_WEBHOOK_URL:
        return

    # Count user messages
    user_msgs = [m for m in save_messages if m.get("role") == "user"]
    if not user_msgs:
        return  # Don't notify for sessions with no user messages

    # Build conversation text for summary from uncompacted save_messages
    convo_lines = []
    for m in save_messages:
        role = m.get("role")
        content = m.get("content", "")[:500]
        convo_lines.append(f"{role}: {content}")

    try:
        summary_response = await asyncio.wait_for(
            asyncio.to_thread(
                summary_client.chat.completions.create,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a conversation summarizer. Produce a brief 2-3 sentence summary of what the visitor was interested in. Do NOT roleplay, continue the conversation, or add meta-commentary."
                    },
                    {
                        "role": "user",
                        "content": "Summarize this conversation:\n\n" + "\n".join(convo_lines[-30:])
                    }
                ],
                model=SUMMARY_MODEL,
                temperature=0.3,
                max_tokens=200
            ),
            timeout=10
        )
        summary = summary_response.choices[0].message.content
    except Exception as e:
        log.warning(f"Discord summary generation failed: {e}")
        summary = f"({len(user_msgs)} messages exchanged, summary unavailable)"

    conv_id_short = conversation_id[:8] if conversation_id else "n/a"
    ended_label = "Idle timeout" if reason == "stale_timeout" else "Clean disconnect"
    embed = {
        "content": "@everyone",
        "embeds": [{
            "title": f"💬 New Conversation Ended",
            "color": 0xF59E0B,  # amber
            "fields": [
                {"name": "Visitor", "value": name, "inline": True},
                {"name": "Email", "value": email, "inline": True},
                {"name": "Messages", "value": str(len(user_msgs)), "inline": True},
                {"name": "ID", "value": conv_id_short, "inline": True},
                {"name": "IP", "value": client_ip or "unknown", "inline": True},
                {"name": "Ended via", "value": ended_label, "inline": True},
                {"name": "Summary", "value": summary[:1024]},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }]
    }

    try:
        await asyncio.to_thread(
            http_requests.post, DISCORD_WEBHOOK_URL, json=embed, timeout=5
        )
        log.info(f"Discord notification sent for {email}")
    except Exception as e:
        log.warning(f"Discord webhook failed: {e}")


# ─── Session Cleanup ─────────────────────────────────────────────────────────

async def cleanup_stale_sessions():
    """Background task: evict sessions idle for more than SESSION_TTL seconds."""
    while True:
        await asyncio.sleep(600)  # run every 10 minutes
        now = time.time()
        stale = [sid for sid, ts in session_last_active.items() if now - ts > SESSION_TTL]
        for sid in stale:
            log.info(f"Evicting stale session: {sid}")
            await _persist_and_cleanup(sid, reason="stale_timeout")
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
        if isinstance(data, str):
            data = json.loads(data)
        data["conversation_id"] = str(uuid.uuid4())
        user_map[sid] = data
        log.info(f"Conversation ID: {data['conversation_id']}")
    session_last_active[sid] = time.time()
    await sio.emit("message", {
        "text": "Hey! I'm Archit — or well, a digital version of me. Ask me anything about my work, projects, or my questionable anime taste. What's up?"
    }, to=sid)


async def message_service(sid, message: str):
    session_last_active[sid] = time.time()

    # Initialize history for new sessions
    if sid not in message_histories:
        message_histories[sid] = [{"role": "system", "content": prompt}]
        save_histories[sid] = []

    # Add the user's message
    message_histories[sid].append({"role": "user", "content": message})
    save_histories.setdefault(sid, []).append({
        "role": "user", "content": message, "timestamp": datetime.now().isoformat()
    })

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
                save_tool_calls.setdefault(sid, []).append({
                    "name": tool_name, "args": tool_args, "timestamp": datetime.now().isoformat()
                })

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
            save_histories.setdefault(sid, []).append({
                "role": "assistant", "content": content, "timestamp": datetime.now().isoformat()
            })
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

                if full_content:
                    content = _sanitize_response(full_content)
                    message_histories[sid].append({"role": "assistant", "content": content})
                    save_histories.setdefault(sid, []).append({
                        "role": "assistant", "content": content, "timestamp": datetime.now().isoformat()
                    })
                    await sio.emit("stream_end", {}, to=sid)
                    log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Streamed Response: [{content[:100]}...]")
                else:
                    # Empty stream — fall back to a canned reply (saved + emitted)
                    log.warning(f"Empty stream for {sid}, using canned fallback")
                    await _emit_and_save_canned(sid, "stream_fallback")
            except Exception as stream_err:
                log.warning(f"Streaming failed, falling back: {stream_err}")
                await _emit_and_save_canned(sid, "stream_fallback")

    except asyncio.TimeoutError:
        log.error(f"LLM call timed out for {sid}")
        await _emit_and_save_canned(sid, "timeout")
    except Exception as e:
        log.error(f"Exception in message_service: {e}", exc_info=True)
        await _emit_and_save_canned(sid, "generic_error")


async def _persist_and_cleanup(sid, reason: str = "disconnect"):
    """Save conversation to MongoDB, notify Discord, and free memory.

    Shared by both clean disconnects and stale-session eviction.
    `reason` is surfaced in logs to distinguish the two paths.
    """
    try:
        if sid not in message_histories or sid not in user_map:
            log.info(f"No data found for sid: {sid} ({reason})")
            return

        user_data = user_map[sid]
        if isinstance(user_data, str):
            user_data = json.loads(user_data)
        name = user_data.get("name", "Unknown User")
        email = user_data.get("email", "unknown@unknown")
        conversation_id = user_data.get("conversation_id")
        client_ip = session_ips.get(sid)

        # Use save_histories (full, uncompacted conversation) for storage
        structured_messages = save_histories.get(sid, [])
        tool_calls_log = save_tool_calls.get(sid, [])

        # Retry with fallback to local file
        saved = False
        for attempt in range(2):
            try:
                async with get_db() as db:
                    await add_history(db=db, name=name, email=email,
                                      messages=structured_messages, conversation_id=conversation_id,
                                      tool_calls=tool_calls_log, client_ip=client_ip)
                saved = True
                log.info(f"Saved conversation for {email} ({reason})")
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
                    "conversation_id": conversation_id,
                    "client_ip": client_ip,
                    "messages": structured_messages,
                    "tool_calls": tool_calls_log,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat()
                }
                fallback_path = Path("logs/failed_saves.jsonl")
                fallback_path.parent.mkdir(parents=True, exist_ok=True)
                with open(fallback_path, "a") as f:
                    f.write(json.dumps(fallback) + "\n")
                log.info(f"Wrote fallback history for {email} to {fallback_path}")
            except Exception as file_err:
                log.error(f"Fallback file write also failed: {file_err}")

        # Send Discord notification (fire-and-forget, don't block cleanup)
        try:
            await _notify_discord(name, email, structured_messages, conversation_id, reason=reason, client_ip=client_ip)
        except Exception as notif_err:
            log.warning(f"Discord notification failed: {notif_err}")

    except Exception as e:
        log.error(f"Error in _persist_and_cleanup ({reason}): {e}", exc_info=True)
    finally:
        # Always clean up memory
        message_histories.pop(sid, None)
        save_histories.pop(sid, None)
        save_tool_calls.pop(sid, None)
        user_map.pop(sid, None)
        session_last_active.pop(sid, None)
        session_ips.pop(sid, None)


async def disconnect_service(sid):
    await _persist_and_cleanup(sid, reason="disconnect")
