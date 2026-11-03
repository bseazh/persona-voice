"""Ephemeral phone conversation view; no audio or text is written to logs."""
import json
import logging
import os
from pathlib import Path
import re
import time

DIRECTORY = Path('/run/persona-phone-transcripts')


def attach_phone_transcript(session, room_name):
    if not room_name.startswith('sim-ai-') or not DIRECTORY.is_dir():
        return
    if not re.fullmatch(r'[A-Za-z0-9_-]+', room_name):
        return
    path = DIRECTORY / (room_name + '.json')
    state = {'room': room_name, 'started_at': time.time(), 'updated_at': time.time(),
             'active': True, 'messages': []}

    def save():
        state['updated_at'] = time.time()
        temporary = path.with_suffix('.tmp')
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
            with os.fdopen(fd, 'w') as out:
                json.dump(state, out, ensure_ascii=False)
            os.replace(temporary, path)
        except OSError:
            logging.getLogger(__name__).warning('Phone transcript view unavailable')

    @session.on('conversation_item_added')
    def item_added(event):
        item = event.item
        if item.role not in ('user', 'assistant') or not item.text_content:
            return
        message = {'id': item.id, 'role': item.role, 'text': item.text_content[:8000],
                   'at': time.time(), 'interrupted': bool(getattr(item, 'interrupted', False))}
        state['messages'] = [m for m in state['messages'] if m['id'] != item.id]
        state['messages'].append(message)
        state['messages'] = state['messages'][-200:]
        save()

    @session.on('close')
    def closed(event):
        state['active'] = False
        save()

    save()
