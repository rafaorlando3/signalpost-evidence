import json
from pathlib import Path
import sys
import tempfile
import unittest
import time
import subprocess
from unittest.mock import patch
from evaluator import collect


class Deadline(unittest.TestCase):
    def run_child(self, text, rows, timeout=2, await_prefix=False):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)/'out.jsonl'
            code = 'from pathlib import Path\nimport time\np=Path('+repr(str(output))+')\n'+text
            command=[sys.executable,'-c',code]
            if not await_prefix:
                return collect(command,output,rows,timeout,Path(d)/'log')
            original=subprocess.Popen;observed=[]
            def launch(*args,**kwargs):
                process=original(*args,**kwargs);until=time.monotonic()+5
                while time.monotonic()<until:
                    if output.exists() and output.read_text().endswith(chr(10)+'{'):
                        observed.append(True);return process
                    if process.poll() is not None:break
                    time.sleep(.005)
                from evaluator import stop
                stop(process)
                self.fail('child did not publish prefix before readiness deadline')
            with patch('evaluator.subprocess.Popen',side_effect=launch):
                result=collect(command,output,rows,timeout,Path(d)/'log')
            self.assertEqual(observed,[True])
            return result

    def test_timeout_preserves_completed_prefix_and_emits_failed_remaining(self):
        envelope = {'organisation_number':'one','run':{'terminal_status':'completed'},'claims':[]}
        text = 'p.write_text('+repr(json.dumps(envelope)+'\n{')+')\ntime.sleep(20)'
        rows, report = self.run_child(text,[{'organisation_number':'one'},{'organisation_number':'two'}],.3,await_prefix=True)
        self.assertTrue(report['wall_clock_timeout'])
        self.assertLess(report['runtime_seconds'],7)
        self.assertEqual(rows[0],envelope)
        self.assertEqual(rows[1]['run']['terminal_status'],'failed')
        self.assertEqual(rows[1]['operations']['requests'],20)
        self.assertTrue(rows[1]['operations']['requests_are_upper_bound'])

    def test_wrong_company_output_is_not_accepted(self):
        bad = {'organisation_number':'wrong','run':{'terminal_status':'completed'}}
        rows, report = self.run_child('p.write_text('+repr(json.dumps(bad)+'\n')+')',[{'organisation_number':'one'}])
        self.assertEqual(report['preserved_outputs'],0)
        self.assertEqual(rows[0]['organisation_number'],'one')
        self.assertEqual(rows[0]['run']['terminal_status'],'failed')

    def test_success_does_not_create_failures(self):
        good = {'organisation_number':'one','run':{'terminal_status':'completed'}}
        rows, report = self.run_child('p.write_text('+repr(json.dumps(good)+'\n')+')',[{'organisation_number':'one'}])
        self.assertEqual(rows,[good]); self.assertFalse(report['wall_clock_timeout'])
        self.assertEqual(report['synthesized_failures'],0)

    def test_malformed_complete_json_preserves_good_prefix_and_returns_failures(self):
        good = {'organisation_number':'one','run':{'terminal_status':'completed'}}
        for bad in (None, [], 'invalid', {'organisation_number':'two','run':None}):
            with self.subTest(bad=bad):
                text = json.dumps(good)+'\n'+json.dumps(bad)+'\n'
                rows, report = self.run_child('p.write_text('+repr(text)+')',
                    [{'organisation_number':'one'},{'organisation_number':'two'}])
                self.assertEqual(rows[0],good)
                self.assertEqual(rows[1]['run']['terminal_status'],'failed')
                self.assertEqual(report['preserved_outputs'],1)
                self.assertEqual(report['synthesized_failures'],1)

if __name__=='__main__':unittest.main()
