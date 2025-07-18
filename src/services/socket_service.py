import os
import json
import traceback
from datetime import datetime
from groq import Groq
from dotenv import load_dotenv
from src.utils.prompt_template import prompt
from src.config.socket_config import create_socketio_app
from src.utils.tool_description_list import tools
from src.utils.tool_utils import tool_map
from src.repository.history_repository import add_history
from src.config.db_config import get_db
from src.logger import get_logger

log = get_logger(__name__)

load_dotenv()

client = Groq(
    api_key=os.getenv("API_KEY"),
)

sio = create_socketio_app()
message_histories = {}
user_map = {}


async def start_service(sid, data):
    if sid not in user_map:
        log.info(f"Start Data: {data}")
        user_map[sid] = data
    await sio.emit("message", {"text": "Hi there! I'm Archit's digital clone. Feel free to ask about my skills, projects, or interests in software development. How can I help you learn more about me today?"}, to=sid)


async def message_service(sid, message: str):
    # Initialize history for new sessions
    if sid not in message_histories:
        # user_map[sid] =
        message_histories[sid] = [
            {"role": "system", "content": prompt}
        ]

    # Add the user's message to the history
    message_histories[sid].append({"role": "user", "content": message})
    try:
        # Call the LLM with the current history
        response = client.chat.completions.create(
            messages=message_histories[sid],
            model="deepseek-r1-distill-llama-70b",
            tools=tools,
            tool_choice="auto",
            temperature=0.7
        )
        response_message = response.choices[0].message

        # Handle tool calls (loop in case of multiple tool calls in a row)
        while hasattr(response_message, "tool_calls") and response_message.tool_calls:
            log.info(len(response_message.tool_calls))
            for tool_call in response_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                tool = tool_map[tool_name]
                log.info(f"[{tool_name}] tool called with arguments: {tool_args}")
                # If your tool functions are async, use: tool_result = await tool(**tool_args)
                tool_result = tool(**tool_args)
                log.info(f"[{tool_name}] tool result: {tool_result}")
                # Add the tool response to the history as a function message
                message_histories[sid].append({
                    "role": "function",
                    "name": tool_name,
                    "content": json.dumps({
                        "result": tool_result,
                        "status": "success",
                        "is_final": True  # Signal that no further calls are needed
                    })
                })
            log.info("All tool calls done")
            # Call the LLM again, now with the tool result(s) in the history
            response = client.chat.completions.create(
                messages=message_histories[sid],
                model="qwen-qwq-32b",
                tools=tools,
                tool_choice="auto"
            )
            log.info(response)
            response_message = response.choices[0].message

        # Add the assistant's response to the history
        message_histories[sid].append({
            "role": "assistant",
            "content": response_message.content
        })

        log.info(f"[{datetime.now().strftime('%A, %d-%m-%Y %H:%M:%S')}] Emitting Response: [{response_message.content}]")
        await sio.emit("message", {"text": response_message.content}, to=sid)
    except Exception as e:
        log.error(f"Exception in message_service: {e.__traceback__}", exc_info=e.__traceback__)
        await sio.emit("message", {"text": "It seems like something went wrong. Please Try Again Later."}, to=sid)


async def disconnect_service(sid):
    if sid not in message_histories or sid not in user_map:
        log.info("No data found for this sid.")
        return

    name = json.loads(user_map[sid]).get("name", "Unknown User")  # adapt this key as needed
    email = json.loads(user_map[sid]).get("email", "ok@ok")

    history = message_histories[sid]

    conversation_lines = []
    for entry in history:
        role = entry.get("role")
        content = entry.get("content", "")

        if role == "system":
            # Optional: skip or include system prompts
            continue
        elif role == "user":
            conversation_lines.append(f"User: {content}")
        elif role == "assistant":
            conversation_lines.append(f"Assistant: {content}")
        elif role == "function":
            # Tool or function call response — you might want to include this or skip it
            # Here, I add it in brackets to differentiate
            conversation_lines.append(f"[Function {entry.get('name')} Response]: {content}")

    conversation_text = "\n\n".join(conversation_lines)
    async with get_db() as db:
        await add_history(db=db, name=name, email=email, history=conversation_text)
    # return username, conversation_text
