import json
import os
import subprocess
from pathlib import Path
from unittest import mock
from django.test import TestCase, SimpleTestCase
from aso import codex_ai, run_queue, search_jobs
from aso.models import CodexRun, KeywordSearchJob


class CodexAdapterTest(SimpleTestCase):
    def test_subprocess_uses_subscription_and_validates_output(self):
        report = {"analysis":"Useful report", "keywords":["golf","golf"], "title":"A"*31,
                  "subtitle":"Swing tools", "keyword_field":"swing,video", "cautions":[]}
        def fake(args, **kwargs):
            self.assertNotIn("OPENAI_API_KEY",kwargs['env'])
            self.assertIn('forced_login_method="chatgpt"',args)
            self.assertIn('--ignore-user-config',args)
            self.assertIn('read-only',args)
            self.assertEqual(kwargs['input'],'Analyze facts')
            Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(report))
            return subprocess.CompletedProcess(args,0,'','')
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY':'should-never-be-forwarded'}), mock.patch.object(codex_ai,'connection_status',return_value={'connected':True}), mock.patch.object(codex_ai,'executable',return_value='/codex'), mock.patch.object(codex_ai.subprocess,'run',side_effect=fake):
            result=codex_ai.ask_codex('Analyze facts')
        self.assertEqual(result['keywords'],['golf'])
        self.assertIn('31 characters',result['cautions'][0])

    def test_api_key_login_is_rejected(self):
        with mock.patch.object(codex_ai,'executable',return_value='/codex'), mock.patch.object(codex_ai.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'Logged in using an API key','')):
            self.assertFalse(codex_ai.connection_status()['connected'])

    def test_provider_error_does_not_leak_output(self):
        with mock.patch.object(codex_ai,'connection_status',return_value={'connected':True}), mock.patch.object(codex_ai,'executable',return_value='/codex'), mock.patch.object(codex_ai.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'secret diagnostic','')):
            with self.assertRaisesRegex(RuntimeError,'could not complete') as raised:
                codex_ai.ask_codex('brief')
            self.assertNotIn('secret',str(raised.exception))


class CodexWorkflowTest(TestCase):
    def test_validation_and_csrf(self):
        self.assertEqual(self.client.post('/codex/runs/',{'brief':'x'}).status_code,400)
        from django.test import Client
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/codex/runs/',{'brief':'valid brief'}).status_code,403)
        self.assertEqual(self.client.get('/codex/runs/1/retry/').status_code,405)

    def test_queue_and_failed_run_retry(self):
        with mock.patch.object(codex_ai,'connection_status',return_value={'connected':True}), mock.patch.object(run_queue,'kick'):
            r=self.client.post('/codex/runs/',{'brief':'An app for golf video','mode':'research','country':'us'})
            self.assertEqual(r.status_code,202)
            pk=r.json()['id']
            self.assertEqual(self.client.post(f'/codex/runs/{pk}/retry/').status_code,409)
            CodexRun.objects.filter(pk=pk).update(status='failed',report={'stale':True},evidence=[{'stale':True}])
            self.assertEqual(self.client.post(f'/codex/runs/{pk}/retry/').status_code,202)
            fresh=CodexRun.objects.get(pk=pk)
            self.assertEqual(fresh.report,{})
            self.assertEqual(fresh.evidence,[])

    def test_report_persists_and_failures_are_visible(self):
        row=CodexRun.objects.create(mode='metadata',brief='Golf video app',status='running')
        with mock.patch('aso.research_pipeline.run',return_value=({'analysis':'Review'},[],{})):
            codex_ai.execute(row.pk)
        row.refresh_from_db();self.assertEqual(row.status,'completed');self.assertEqual(row.report['analysis'],'Review')
        with mock.patch('aso.research_pipeline.run',side_effect=RuntimeError('Usage limit reached')):
            codex_ai.execute(row.pk)
        row.refresh_from_db();self.assertEqual(row.status,'failed');self.assertEqual(row.error_message,'Usage limit reached')

    def test_public_search_queue_is_not_license_gated(self):
        self.assertEqual(search_jobs.keyword_limit(),1000)
        KeywordSearchJob.objects.create(keywords=['existing'],countries=['us'],status='running')
        with mock.patch.object(run_queue,'kick'):
            r=self.client.post('/search/', {'keywords':'one,two,three,four,five','countries':'us'})
        self.assertLess(r.status_code,300)
        self.assertEqual(KeywordSearchJob.objects.count(),2)
