"""Keep completed question/answer turns atomic and ordered per conversation."""

from psycopg.types.json import Jsonb

from db import documents as store
from documents.models import DocumentError


def list_conversations():
    with store.connect() as conn:
        return conn.execute("""SELECT id, title, updated_at FROM knowledge_base_v1.conversations
            ORDER BY updated_at DESC, id DESC""").fetchall()


def get_conversation(conversation_id):
    with store.connect() as conn:
        result = conn.execute("""SELECT c.id, c.title, c.updated_at,
            COALESCE(jsonb_agg(jsonb_build_object('id', t.id, 'question', t.question,
                'depth', t.depth, 'answer', t.answer) ORDER BY t.turn_index)
                FILTER (WHERE t.id IS NOT NULL), '[]'::jsonb) AS turns
            FROM knowledge_base_v1.conversations c
            LEFT JOIN knowledge_base_v1.conversation_turns t ON t.conversation_id=c.id
            WHERE c.id=%s GROUP BY c.id""", (conversation_id,)).fetchone()
    if result is None:
        raise DocumentError("conversation_missing", "找不到这个会话。", 404)
    return result


def delete_conversation(conversation_id):
    with store.connect() as conn:
        conn.execute("DELETE FROM knowledge_base_v1.conversations WHERE id=%s", (conversation_id,))


def _conversation(conn, conversation_id, *, locked=False):
    query = "SELECT id, title, updated_at FROM knowledge_base_v1.conversations WHERE id=%s"
    return conn.execute(query + (" FOR UPDATE" if locked else ""), (conversation_id,)).fetchone()


def _previous_result(conn, conversation, request):
    if conversation is None:
        return None
    turn = conn.execute("""SELECT id, question, depth, answer FROM knowledge_base_v1.conversation_turns
        WHERE conversation_id=%s AND id=%s""", (conversation["id"], request.request_id)).fetchone()
    if turn is None:
        return None
    if (turn["question"], turn["depth"]) != (request.question, request.depth):
        raise DocumentError("conversation_conflict", "这个请求编号已用于另一条提问。", 409)
    return {"conversation": conversation, "turn": turn}


def _check_parent(conversation, turns, request, creating):
    if conversation is None and not creating:
        raise DocumentError("conversation_missing", "找不到这个会话。", 404)
    current = turns[0]["id"] if turns else None
    if current != getattr(request, "after_turn_id", None):
        raise DocumentError("conversation_conflict", "会话已有新消息，请刷新后继续。", 409)


def prepare_turn(conversation_id, request, *, creating):
    with store.connect() as conn, conn.transaction():
        # Read a single snapshot, then release the transaction before calling Gemini.
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conversation = _conversation(conn, conversation_id)
        previous = _previous_result(conn, conversation, request)
        if previous is not None:
            return previous, []
        turns = conn.execute("""SELECT id, question, answer FROM knowledge_base_v1.conversation_turns
            WHERE conversation_id=%s ORDER BY turn_index DESC LIMIT 3""", (conversation_id,)).fetchall()
        _check_parent(conversation, turns, request, creating)
        return None, turns[::-1]


def save_turn(conversation_id, request, answer, *, creating):
    with store.connect() as conn, conn.transaction():
        if creating:
            title = " ".join(request.question.split())[:60]
            conn.execute("""INSERT INTO knowledge_base_v1.conversations (id, title) VALUES (%s, %s)
                ON CONFLICT (id) DO NOTHING""", (conversation_id, title))
        conversation = _conversation(conn, conversation_id, locked=True)
        previous = _previous_result(conn, conversation, request)
        if previous is not None:
            return previous
        latest = conn.execute("""SELECT id, turn_index FROM knowledge_base_v1.conversation_turns
            WHERE conversation_id=%s ORDER BY turn_index DESC LIMIT 1""", (conversation_id,)).fetchone()
        _check_parent(conversation, [latest] if latest else [], request, creating)
        turn = conn.execute("""INSERT INTO knowledge_base_v1.conversation_turns
            (conversation_id, id, turn_index, question, depth, answer) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, question, depth, answer""",
            (conversation_id, request.request_id, latest["turn_index"] + 1 if latest else 1,
             request.question, request.depth, Jsonb(answer))).fetchone()
        conversation = conn.execute("""UPDATE knowledge_base_v1.conversations SET updated_at=now()
            WHERE id=%s RETURNING id, title, updated_at""", (conversation_id,)).fetchone()
    return {"conversation": conversation, "turn": turn}
