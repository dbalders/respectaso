from unittest import mock
from django.test import SimpleTestCase, TestCase
from aso.apple_ads import discovery, api
from aso.research_pipeline import app_id_from_input, metadata_checks, run
from aso.models import CodexRun

REPORT={'analysis':'Findings','keywords':['golf swing'],'title':'Golf Video','subtitle':'Compare Your Swing','keyword_field':'posture,lines','cautions':[]}

class DiscoveryTest(SimpleTestCase):
    def query(self, response):
        with mock.patch.object(discovery.storage,'api_credentials',return_value={'private_key_pem':'never serialize'}), mock.patch.object(discovery.storage,'load_apple_settings',return_value={'apple_ads':{'ad_account_id':'123'}}), mock.patch.object(api,'_request',return_value=response) as request:
            result=discovery._query('keywords',[discovery._filter('promotedObjectId','42')],'US')
        self.assertNotIn('never serialize',str(result))
        self.assertEqual(request.call_args.args[:2],('POST','/suggestions/keywords/query'))
        return result

    def test_normalizes_real_values_and_preserves_request(self):
        data=self.query({'result':[{'text':'golf swing','popularity':78}], 'pagination':{'totalCount':100}})
        self.assertEqual(data['candidates'][0]['apple_relative_popularity'],78)
        self.assertEqual(data['candidates'][0]['country'],'US')
        self.assertTrue(data['truncated'])
        self.assertEqual(data['request']['filters'][0]['value'],['42'])

    def test_response_contract_fails_visibly(self):
        with self.assertRaises(RuntimeError):self.query({'result':{'unexpected':[]}})

    def test_missing_credentials_never_makes_network_call(self):
        with mock.patch.object(discovery,'connection_status',return_value={'connected':False}),mock.patch.object(api,'_request') as request:
            data=discovery.discover(seed='golf')
        self.assertEqual(data['status'],'unconfigured');request.assert_not_called()

    def test_phrase_scope_and_keyword_scope_are_distinct(self):
        def query(kind, filters, scope):
            if kind=='phrases':
                self.assertIsNone(scope)
                self.assertNotIn('countriesOrRegions',[f['field'] for f in filters])
            else:self.assertEqual(scope,'US')
            return {'candidates':[{'keyword':'golf','country':scope}],'truncated':False}
        with mock.patch.object(discovery,'connection_status',return_value={'connected':True}),mock.patch.object(discovery,'_query',side_effect=query):
            data=discovery.discover(seed='golf',app_id='42')
        self.assertEqual(len(data['candidates']),2)
        self.assertTrue(any('no documented country' in w for w in data['warnings']))

    def test_permission_failure_is_partial_and_sanitized(self):
        with mock.patch.object(discovery,'connection_status',return_value={'connected':True}), mock.patch.object(discovery,'_query',side_effect=api.AppleAdsAccessError('private diagnostic')):
            data=discovery.discover(seed='golf')
        self.assertEqual(data['status'],'unavailable');self.assertNotIn('private diagnostic',str(data))

    def test_url_validation_blocks_arbitrary_fetches(self):
        self.assertEqual(app_id_from_input('https://apps.apple.com/us/app/example/id123?x=1'),'123')
        for value in ['http://127.0.0.1/id123','https://apps.apple.com.evil.test/id123','42;touch /tmp/x']:
            with self.assertRaises(ValueError):app_id_from_input(value)

    def test_metadata_validation(self):
        self.assertEqual(metadata_checks(REPORT),[])
        bad={**REPORT,'title':'x'*31,'subtitle':'Golf Golf','keyword_field':'golf, swing'}
        issues=metadata_checks(bad)
        self.assertTrue(any('exceeds' in i for i in issues))
        self.assertTrue(any('remove spaces' in i for i in issues))
        self.assertTrue(any('repeated' in i for i in issues))

class PipelineTest(TestCase):
    def test_scoring_is_fed_back_to_codex(self):
        row=CodexRun.objects.create(mode='research',brief='Golf video app',country='us')
        ask=mock.Mock(return_value={**REPORT})
        apple={'status':'available','warnings':[],'snapshots':[], 'candidates':[{'keyword':'golf swing','country':'US','apple_relative_popularity':78}]}
        with mock.patch('aso.research_pipeline.discovery.discover',return_value=apple),mock.patch('aso.research_pipeline.score_keyword_pair',return_value=object()) as score,mock.patch('aso.research_pipeline.AdaptiveITunesRateLimiter'):
            report,evidence,_=run(row,ask,lambda r:{'keyword':'golf swing','difficulty':52})
        self.assertEqual(score.call_count,1)
        self.assertEqual(ask.call_count,2)
        self.assertIn('"difficulty": 52',ask.call_args.args[0])
        self.assertEqual(evidence[0]['candidate_source'],'apple')
        self.assertTrue(report['validation']['passed'])
        self.assertEqual(report['research_summary']['scored_keywords'],1)

    def test_correction_loop_is_bounded(self):
        row=CodexRun.objects.create(mode='metadata',brief='unknown app',country='us')
        bad={**REPORT,'keywords':[],'title':'a'*31}
        ask=mock.Mock(return_value=bad)
        with mock.patch('aso.research_pipeline.discovery.discover',return_value={'status':'unconfigured','warnings':[],'candidates':[],'snapshots':[]}):
            report,_,_=run(row,ask,lambda r:{})
        self.assertEqual(ask.call_count,4)
        self.assertFalse(report['validation']['passed'])


    def test_owned_app_listing_is_available_to_the_model_and_saved(self):
        row=CodexRun.objects.create(mode='research',brief='Golf video app',promoted_app_id='123',country='us')
        ask=mock.Mock(return_value={**REPORT,'keywords':[]})
        with mock.patch('aso.research_pipeline.discovery.discover',return_value={'status':'unconfigured','warnings':[],'candidates':[],'snapshots':[]}), mock.patch('aso.research_pipeline.ITunesSearchService') as service:
            service.return_value.lookup_by_id.return_value={'trackName':'Our App'}
            service.return_value.lookup_full_description.return_value={'description':'Verified app features'}
            _,_,data=run(row,ask,lambda r:{})
        self.assertIn('Verified app features',ask.call_args.args[0])
        self.assertEqual(data['listings']['your_app']['trackName'],'Our App')
