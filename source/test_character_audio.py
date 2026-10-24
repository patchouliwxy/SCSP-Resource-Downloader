import json
from pathlib import Path
import tempfile
import unittest
import wave
import download_character_audio as batch
from test_scsp_web import resource


class CharacterAudioTests(unittest.TestCase):
    def test_role_folders_do_not_guess_unknown_or_multirole_aliases(self):
        names={'01':'櫻木 真乃','02':'風野 灯織'}
        self.assertEqual(batch.role_folder('s01_0001_01mano',names)[0],'01_櫻木 真乃')
        self.assertEqual(batch.role_folder('s01_0001',names),('_unknown',[]))
        self.assertEqual(batch.role_folder('s01_0001_01mano; s01_0001_02hiori',names)[0],'_multiple_roles')
    def test_wav_validation_and_safe_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();p=root/'a.wav'
            with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(b'\x01\x00'*5)
            info={'sampleRate':48000,'channels':1,'numberOfSamples':5}
            self.assertTrue(batch.inspect_wav(p,info)['non_silent'])
            with self.assertRaises(ValueError):batch.inspect_wav(p,{**info,'numberOfSamples':6})
            with self.assertRaises(ValueError):batch.safe_path(root,'../outside')
            self.assertNotIn('/',batch.safe_name('../invalid/name'))
    def test_resume_checks_wav_content_without_overwriting_user_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);e=resource('s01_test.acb');index=dict(game_version='test',resource_version='test',entries=[e])
            manager=batch.Corpus(index,{},root/'out',root/'cache')
            audio=manager.out/'role/a.wav';audio.parent.mkdir();audio.write_bytes(b'original')
            receipt={'identity':batch.fingerprint(e),'complete':True,'tracks':[{'file':'role/a.wav','bytes':8,'sha256':batch.digest(audio)}]}
            batch.save_json(manager.state_path(e),receipt)
            self.assertEqual(manager.resume(e),receipt)
            audio.write_bytes(b'changed!')
            with self.assertRaisesRegex(ValueError,'changed/missing'):manager.resume(e)
            self.assertEqual(audio.read_bytes(),b'changed!')
