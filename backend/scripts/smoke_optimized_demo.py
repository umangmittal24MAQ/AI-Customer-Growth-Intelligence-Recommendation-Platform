"""Local mocked IndiaAI integration smoke test; requires no key/network.

Run: python -m scripts.smoke_optimized_demo
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import types
from app import db, onboarding, config, pipeline, indiaai_client
from app.agents import clients



class FakeCompletions:
    calls = 0
    async def create(self, **kwargs):
        FakeCompletions.calls += 1
        instructions = kwargs['messages'][0]['content']
        if instructions.startswith('You are the Recommendation agent'):
            payload = json.loads(kwargs['messages'][1]['content'])
            products = payload.get('candidate_products') or []
            if not products:
                raise AssertionError('No candidates sent')
            response = {'product': products[0]['product_name'], 'segment': 'growth',
                        'churn_risk': 'low', 'churn_reason': 'Stable account',
                        'rationale': 'Rising engagement supports evaluating the next tier.',
                        'revenue_score': 78, 'confidence': 0.78}
        elif instructions.startswith('You are the Critic agent'):
            response = {'approved': True, 'revised_churn_risk': 'low',
                        'veto_reason': None, 'churn_risk_reason': 'No significant decline',
                        'confidence_penalty': 0.0}
        else:
            raise AssertionError('Unexpected LLM agent call: ' + instructions[:150])
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=json.dumps(response)))])

class FakeIndiaAI:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeCompletions())
    async def close(self):
        pass


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db.DB_PATH = str(Path(tmp)/'traject-test.db')
        db.init_db()
        tenant='traject-showcase'
        login=onboarding.login_or_provision(tenant)
        customers=db.get_customers(tenant)
        catalog=db.get_product_catalog(tenant)
        assert len(customers)==12 and len(catalog)==12
        config.INDIAAI_API_KEY = 'test-key-in-memory'
        
        clients.make_client = lambda *, asynchronous=False: FakeIndiaAI()
        class FakeSync:
            def close(self): pass
        indiaai_client.make_client = lambda *, asynchronous=False: FakeSync()
        results=pipeline.generate_recommendations(tenant_id=tenant,
            customer_ids=['DEMO-001','DEMO-002','DEMO-007','DEMO-008','DEMO-010'],
            force_include=True, include_null_results=True)
        indexed={r['customer_id']:r for r in results}
        assert len(indexed)==5, indexed.keys()
        assert indexed['DEMO-001']['recommended_product'] in ('Growth','Scale')
        assert indexed['DEMO-002']['recommended_product'] in ('Scale','Enterprise')
        for cid in ('DEMO-007','DEMO-008','DEMO-010'):
            assert indexed[cid]['recommended_product'] is None, (cid, indexed[cid])
            assert indexed[cid]['estimated_deal_value']==0
            assert indexed[cid]['no_recommendation_reason_code']
        for rec in results:
            assert rec['recommended_product'] not in ('Tennis Coaching Plan','Retail POS Terminal','Medical Claims System')
        print('INTEGRATION_OK: customers=12, products=12, analyzed=5, IndiaAI_mock_calls='+str(FakeCompletions.calls))
        for r in sorted(results,key=lambda r:r['customer_id']):
            print(r['customer_id'], r['recommended_product'],r['no_recommendation_reason_code'],
                  (r.get('agent_trace') or {}).get('decision_status'))

if __name__=='__main__':
    main()
