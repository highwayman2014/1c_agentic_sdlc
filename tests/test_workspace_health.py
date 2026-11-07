import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from workspace_health import assess, check_layout, payload, redact, semantic_verified, live_progress_path, demand_probe_admissible
from unittest.mock import patch


def response(kind, state):
    return {'structuredContent': {'state': state, 'indexing': {'targets': [{'kind': kind, 'state': state}]}}}


class HealthTests(unittest.TestCase):
    def test_lexical_ready_does_not_prove_semantic_ready(self):
        statuses = {k: response('lexical' if k=='search' else k, 'ready') for k in ('search','metadata','diagnostics','graph')}
        statuses['search']['structuredContent']['indexing']['targets'].append({'kind':'semantic','state':'disabled'})
        self.assertEqual(assess(statuses)[0], 0)
        self.assertEqual(assess(statuses, True)[0], 2)
        statuses['graph']=response('graph','failed')
        self.assertEqual(assess(statuses)[0], 1)

    def test_unpublished_engine_transient_is_not_a_published_runtime_failure(self):
        statuses={k:response(k,'ready') for k in ('search','graph','metadata','diagnostics')}
        statuses['search']={'structuredContent':{'state':'loading','indexing':{'targets':[
            {'kind':'lexical','state':'waiting','reason_code':'initializing'},
            {'kind':'semantic','state':'failed','reason_code':'native_failure','pass_id':None}]}}}
        self.assertEqual(assess(statuses,True)[0],2)
        statuses['search']['structuredContent']['state']='ready'
        self.assertEqual(assess(statuses,True)[0],1)

    def test_loading_is_not_transport_failure(self):
        statuses={k:response(k,'loading') for k in ('search','graph','metadata','diagnostics')}
        self.assertEqual(assess(statuses)[0],2)

    def test_real_semantics_requires_modality_and_completeness(self):
        r={'structuredContent':{'hits':[{'modality':'L'}], 'freshness':{'completeness':{'status':'complete'}}}}
        self.assertFalse(semantic_verified(r))
        r['structuredContent']['hits'][0]['modality']='S'
        self.assertTrue(semantic_verified(r))
        r['structuredContent']['freshness']['completeness']['status']='partial'
        self.assertFalse(semantic_verified(r))

    def test_demand_probe_handles_missing_last_query_evidence_only(self):
        statuses={k:response('lexical' if k=='search' else k,'ready') for k in ('search','graph','metadata','diagnostics')}
        targets=statuses['search']['structuredContent']['indexing']['targets']
        targets[0].update(state='unknown',reason_code='snapshot_unavailable',phase=None)
        targets.append({'kind':'semantic','state':'ready'})
        self.assertTrue(demand_probe_admissible(statuses))
        targets[1].update(state='running',phase='embedding')
        self.assertFalse(demand_probe_admissible(statuses))
        targets[1].update(state='disabled',phase=None)
        self.assertFalse(demand_probe_admissible(statuses))

    def test_overall_ready_does_not_invent_unknown_semantic_state(self):
        statuses={k:response('lexical' if k=='search' else k,'ready') for k in ('search','graph','metadata','diagnostics')}
        self.assertEqual(assess(statuses,True)[0],2)
        self.assertFalse(demand_probe_admissible(statuses))

    def test_text_json_status_is_supported(self):
        self.assertEqual(payload({'content':[{'type':'text','text':'{"state":"ready"}'}]})['state'],'ready')

    def test_missing_extension_is_a_preflight_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'src/cf').mkdir(parents=True);(root/'src/cf/Configuration.xml').write_text('<Configuration/>')
            (root/'bsl-analyzer.toml').write_text('[source]\nroot="src/cf"\nextensions=[{name="x",path="src/cfe/x"}]\n')
            with self.assertRaisesRegex(ValueError,'root missing'):check_layout(root)
            (root/'src/cfe/x').mkdir(parents=True)
            backend,roots=check_layout(root)
            self.assertEqual(backend,'sqlite');self.assertEqual(len(roots),2)

    def test_live_progress_does_not_rewrite_files_in_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'project';requested=root/'tasks/health.json';outside=base/'live'
            with patch('workspace_health.tempfile.mkdtemp',return_value=str(outside)):
                live=live_progress_path(root,requested,600)
            self.assertEqual(live,outside/'health.json')
            self.assertFalse(live.is_relative_to(root))
            self.assertFalse(requested.exists())
            self.assertIsNone(live_progress_path(root,requested,0))

    def test_external_progress_path_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);requested=base/'outside/health.json'
            self.assertEqual(live_progress_path(base/'project',requested,600),requested.resolve())

    def test_diagnostics_redact_credentials(self):
        text=redact('Authorization: Bearer fixture-secret password=fixture-password token=fixture-token')
        self.assertNotIn('fixture-secret',text);self.assertNotIn('fixture-password',text);self.assertNotIn('fixture-token',text)


if __name__=='__main__': unittest.main()
