# ruff: noqa: E501
CLASSIFY_SYSTEM = """\
Classify this Telegram message as signal or noise.

SIGNAL if it contains any of:
- commitment: a promise or obligation
- pending_reply: waiting for a response that hasn't come
- communication_risk: conflict, missed deadline, tension, or misunderstanding

Output ONLY valid JSON, no markdown, no explanation:
{"is_signal":<bool>,"confidence":<0.0-1.0>,"signal_types":[<"commitment"|"pending_reply"|"communication_risk">]}

If is_signal is false, signal_types must be [].
"""

CLASSIFY_USER = """\
Sender: {sender_name}
Message: {text}
"""

# ── Batch classify ────────────────────────────────────────────────────────────

CLASSIFY_BATCH_SYSTEM = """\
Classify each Telegram message as signal or noise.

SIGNAL if it contains any of:
- commitment: a promise or obligation
- pending_reply: waiting for a response that hasn't come
- communication_risk: conflict, missed deadline, tension, or misunderstanding

Return a JSON array — one entry per message, same order as input:
[{"idx":1,"is_signal":true,"confidence":0.9,"signal_types":["commitment"]},{"idx":2,"is_signal":false,"confidence":0.95,"signal_types":[]}]

Rules:
- idx must equal the input number exactly
- if is_signal is false, signal_types must be []
- output ONLY the JSON array, no markdown, no explanation
"""

CLASSIFY_BATCH_USER = "{items}"
