import importlib.util
from pathlib import Path
import unittest
from flask import Flask

spec = importlib.util.spec_from_file_location('chat', Path(__file__).resolve().parents[1] / 'src/watchparty_chat.py')
chat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chat)

class ChatTests(unittest.TestCase):
    def setUp(self):
        self.session = {'status': 'active', 'host_profile_id': 'h', 'guest_profile_id': 'g', 'host_name': 'Host test', 'guest_name': 'Guest test', 'last_action':'wp4:unchanged'}
        app = Flask(__name__)
        chat.register_watchparty_chat(app, lambda room: self.session if room in ('room', 'other') else None)
        self.host = app.test_client()
        self.guest = app.test_client()
    def params(self, role='host', **extra):
        return {'session_id':'room','role':role,'profile_id':'h' if role == 'host' else 'g', **extra}
    def test_two_clients_exchange_and_cursor(self):
        a = self.host.post('/api/watchparty/chat', json=self.params(text='Ciao!',client_id='one'))
        self.assertEqual(a.status_code,200)
        got = self.guest.get('/api/watchparty/chat',query_string=self.params('guest')).json
        self.assertEqual(got['messages'][0]['text'],'Ciao!')
        b = self.guest.post('/api/watchparty/chat',json=self.params('guest',text='Ciao anche a te',client_id='two'))
        self.assertEqual(b.status_code,200)
        got = self.host.get('/api/watchparty/chat',query_string=self.params(after=1)).json
        self.assertEqual([m['text'] for m in got['messages']],['Ciao anche a te'])
        self.assertEqual(self.session['last_action'],'wp4:unchanged')
    def test_room_isolation_and_idempotency(self):
        payload=self.params(text='Una volta',client_id='retry')
        first=self.host.post('/api/watchparty/chat',json=payload).json
        retry=self.host.post('/api/watchparty/chat',json=payload).json
        self.assertEqual(first,retry)
        self.assertEqual(len(self.guest.get('/api/watchparty/chat',query_string=self.params('guest')).json['messages']),1)
        self.assertEqual(self.guest.get('/api/watchparty/chat',query_string=self.params('guest',session_id='other')).json['messages'],[])
    def test_invalid_messages_membership_and_closed_room(self):
        self.assertEqual(self.host.post('/api/watchparty/chat',json=self.params(text=' ',client_id='empty')).status_code,400)
        self.assertEqual(self.host.post('/api/watchparty/chat',json=self.params(text='x'*1001,client_id='long')).status_code,400)
        self.assertEqual(self.host.get('/api/watchparty/chat',query_string=self.params(profile_id='intruder')).status_code,403)
        self.session['status']='ended'
        self.assertEqual(self.host.get('/api/watchparty/chat',query_string=self.params()).status_code,410)
    def test_rate_limit_and_text_preservation(self):
        body='<img src=x onerror=alert(1)>'
        self.assertEqual(self.host.post('/api/watchparty/chat',json=self.params(text=body,client_id='html')).json['message']['text'],body)
        self.assertEqual(self.host.post('/api/watchparty/chat',json=self.params(text='Troppo presto',client_id='fast')).status_code,429)

if __name__ == '__main__':
    unittest.main()
