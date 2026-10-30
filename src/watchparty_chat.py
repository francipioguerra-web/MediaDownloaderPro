"""Ephemeral room chat, independent of playback state and its write path."""
import threading
import time
from flask import request, jsonify


def register_watchparty_chat(app, lookup_session):
    rooms = {}
    lock = threading.RLock()

    @app.route('/api/watchparty/chat', methods=['GET', 'POST'])
    def watchparty_chat():
        data = (request.get_json(silent=True) or {}) if request.method == 'POST' else request.args
        room_id = str(data.get('session_id', ''))[:100]
        profile_id = str(data.get('profile_id', ''))[:100]
        role = data.get('role')
        if not room_id or not profile_id or role not in ('host', 'guest'):
            return jsonify(success=False, error='Partecipante o stanza non validi'), 400
        session = lookup_session(room_id)
        if not session:
            return jsonify(success=False, error='Chat temporaneamente non disponibile'), 503
        if session.get('status') not in ('waiting', 'active'):
            return jsonify(success=False, error='WatchParty terminata'), 410
        expected = session.get(role + '_profile_id')
        if expected and str(expected) != profile_id:
            return jsonify(success=False, error='Partecipante non presente nella stanza'), 403
        if role == 'host' and not expected:
            return jsonify(success=False, error='Host non valido'), 403
        with lock:
            now = time.time()
            for key in list(rooms):
                if now - rooms[key]['updated'] > 7200:
                    del rooms[key]
            room = rooms.setdefault(room_id, {'messages': [], 'seq': 0, 'updated': now, 'sent': {}})
            room['updated'] = now
            if request.method == 'POST':
                text = data.get('text')
                client_id = data.get('client_id')
                if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                    return jsonify(success=False, error='Scrivi un messaggio di massimo 1000 caratteri'), 400
                if not isinstance(client_id, str) or not client_id or len(client_id) > 100:
                    return jsonify(success=False, error='Identificativo messaggio non valido'), 400
                duplicate = next((m for m in room['messages'] if m['client_id'] == client_id and m['profile_id'] == profile_id), None)
                if duplicate:
                    return jsonify(success=True, message=duplicate)
                if now - room['sent'].get(profile_id, 0) < .5:
                    return jsonify(success=False, error='Attendi un momento prima di inviare ancora'), 429
                room['seq'] += 1
                message = {'id': room['seq'], 'client_id': client_id, 'profile_id': profile_id,
                           'name': session.get(role + '_name') or ('Host' if role == 'host' else 'Ospite'),
                           'role': role, 'text': text.strip(), 'created_at': int(now * 1000)}
                room['messages'].append(message)
                room['messages'] = room['messages'][-200:]
                room['sent'][profile_id] = now
                return jsonify(success=True, message=message)
            try:
                after = max(0, int(data.get('after', 0)))
            except (ValueError, TypeError):
                return jsonify(success=False, error='Cursore non valido'), 400
            return jsonify(success=True, messages=[m for m in room['messages'] if m['id'] > after])
