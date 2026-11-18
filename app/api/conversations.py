"""Saved owner conversations with bounded context for document follow-ups."""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder

from answers.service import answer_question
from api.answers import Question
from api.deps import require_owner
from db import conversations as store

router = APIRouter(prefix="/api/conversations", tags=["conversations"], dependencies=[Depends(require_owner)])


class NewTurn(Question):
    request_id: UUID


class FollowUp(NewTurn):
    after_turn_id: UUID


def respond(conversation_id, request, *, creating):
    previous, history = store.prepare_turn(conversation_id, request, creating=creating)
    if previous is not None:
        return previous
    answer = answer_question(request.question, request.depth, history=history)
    return store.save_turn(conversation_id, request, jsonable_encoder(answer), creating=creating)


@router.get("")
def list_saved():
    return {"items": store.list_conversations()}


@router.post("")
def start(request: NewTurn):
    # The client's first turn ID doubles as the conversation ID, so retrying a
    # response that was saved but lost in transit can recover the same result.
    return respond(request.request_id, request, creating=True)


@router.get("/{conversation_id}")
def get(conversation_id: UUID):
    return store.get_conversation(conversation_id)


@router.post("/{conversation_id}/turns")
def follow_up(conversation_id: UUID, request: FollowUp):
    return respond(conversation_id, request, creating=False)


@router.delete("/{conversation_id}", status_code=204)
def delete(conversation_id: UUID):
    store.delete_conversation(conversation_id)
