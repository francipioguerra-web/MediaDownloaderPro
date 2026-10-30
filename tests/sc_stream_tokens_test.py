import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, parse_qs
from src.sc_stream_tokens import StreamTokens

REF='https://v.vidxgo.co/0141842/1/4'
BASE='https://cdn.v1.test.d2b.you/hls/tv/0141842/1/4/'
NOW=1792596000

def media(name, token, expires):
    return BASE+name+'?t='+token+'&e='+str(int(expires*1000))+'&b=3070'


class TokenTests(unittest.TestCase):
    def test_old_playlist_urls_are_resigned_before_their_token_expires(self):
        clock=[NOW];calls=[]
        def load(ref):
            calls.append(ref)
            return media('master.m3u8','fresh',clock[0]+300)
        tokens=StreamTokens(load,clock=lambda:clock[0])
        original=media('seg-98-v1-a1.ts','old',NOW+300)
        tokens.register(media('master.m3u8','old',NOW+300),REF)
        self.assertEqual(tokens.sign(original,REF),original)
        clock[0]+=275
        updated=tokens.sign(original,REF)
        self.assertEqual(parse_qs(urlsplit(updated).query)['t'],['fresh'])
        self.assertEqual(urlsplit(updated).path,urlsplit(original).path)
        self.assertEqual(parse_qs(urlsplit(updated).query)['b'],['3070'])
        tokens.sign(media('seg-99-v1-a1.ts','old',NOW+300),REF)
        self.assertEqual(calls,[REF])

    def test_403_renews_a_valid_but_rejected_signature_once(self):
        calls=[]
        tokens=StreamTokens(lambda ref:(calls.append(ref) or media('master.m3u8','new',NOW+600)),clock=lambda:NOW)
        denied=media('seg.ts','denied',NOW+300)
        renewed=tokens.sign(denied,REF,force=True)
        self.assertEqual(parse_qs(urlsplit(renewed).query)['t'],['new'])
        self.assertEqual(tokens.sign(denied,REF,force=True),renewed)
        self.assertEqual(len(calls),1)

    def test_parallel_audio_video_and_subtitle_requests_share_one_refresh(self):
        import time
        calls=[]
        def load(ref):
            calls.append(ref);time.sleep(.02)
            return media('master.m3u8','new',NOW+300)
        tokens=StreamTokens(load,clock=lambda:NOW)
        old=media('seg.ts','old',NOW-1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            result=list(pool.map(lambda _:tokens.sign(old,REF),range(8)))
        self.assertEqual(len(set(result)),1)
        self.assertEqual(len(calls),1)

    def test_unrelated_hosts_and_different_episode_cannot_share_tokens(self):
        tokens=StreamTokens(lambda ref:media('master.m3u8','wrong',NOW+300).replace('/1/4/','/1/5/'),clock=lambda:NOW)
        old=media('seg.ts','old',NOW-1)
        self.assertEqual(tokens.sign(old,REF),old)
        self.assertEqual(tokens.sign('https://other.test/video?e=1&t=old',REF),'https://other.test/video?e=1&t=old')
        self.assertEqual(tokens.sign(old,'https://evil.test/'),old)

if __name__=='__main__':unittest.main()
