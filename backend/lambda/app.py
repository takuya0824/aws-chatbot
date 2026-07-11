import json
import os
import time
import uuid

import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ["TABLE_NAME"]
MODEL_ID = os.environ["MODEL_ID"]

HISTORY_TURNS = 10  # number of past user+assistant turns kept as context
TTL_SECONDS = 60 * 60 * 24  # conversation history expires after 1 day

SYSTEM_PROMPT = (
    "You are a friendly, concise assistant. Keep answers short unless the "
    "user asks for more detail."
)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
bedrock = boto3.client("bedrock-runtime")


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _load_history(session_id: str) -> list[dict]:
    result = table.query(
        KeyConditionExpression=Key("session_id").eq(session_id),
        ScanIndexForward=True,
        Limit=HISTORY_TURNS * 2,
    )
    return [
        {"role": item["role"], "content": [{"text": item["text"]}]}
        for item in result.get("Items", [])
    ]


def _save_turn(session_id: str, role: str, text: str, offset_ms: int) -> None:
    now = time.time()
    table.put_item(
        Item={
            "session_id": session_id,
            "timestamp": int(now * 1000) + offset_ms,
            "role": role,
            "text": text,
            "expire_at": int(now) + TTL_SECONDS,
        }
    )


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if method == "OPTIONS":
        return _response(200, {})

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "invalid JSON body"})

    user_message = (body.get("message") or "").strip()
    if not user_message:
        return _response(400, {"error": "message is required"})

    session_id = body.get("session_id") or str(uuid.uuid4())

    history = _load_history(session_id)
    messages = history + [{"role": "user", "content": [{"text": user_message}]}]

    try:
        result = bedrock.converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            inferenceConfig={"maxTokens": 1024, "temperature": 0.7},
        )
    except Exception as exc:
        return _response(502, {"error": f"model invocation failed: {exc}"})

    reply = result["output"]["message"]["content"][0]["text"]

    # offset_ms keeps the user/assistant pair ordered under the same millisecond
    _save_turn(session_id, "user", user_message, offset_ms=0)
    _save_turn(session_id, "assistant", reply, offset_ms=1)

    return _response(200, {"session_id": session_id, "reply": reply})
