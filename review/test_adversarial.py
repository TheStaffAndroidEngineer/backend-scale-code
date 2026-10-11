"""Independent protocol histories; isolated process, temporary database, ephemeral HTTP."""
import concurrent.futures
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from base import Problem, handler
from service import Service

class Review(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.database=Path(self.temp.name)/'state.sqlite'
  self.now=[1_000_000];self.a=Service(self.database,clock=lambda:self.now[0]);self.b=Service(self.database,clock=lambda:self.now[0]);self.servers=[]
 def tearDown(self):
  for server,thread in self.servers:server.shutdown();server.server_close();thread.join(2)
  self.temp.cleanup()
 def body(self,action,args=None,identity=None):return {'id':identity or str(uuid.uuid4()),'action':action,'args':args or {}}
 def run_command(self,body,owner=None):return (owner or self.a).route('POST','/commands',body)[1]
 def command(self,action,args=None,owner=None):return self.run_command(self.body(action,args),owner)
 def view(self,owner=None):return (owner or self.a).route('GET','/view',{})[1]['data']
 def serve(self):
  server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.a));thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01),daemon=True);thread.start();self.servers.append((server,thread));return server.server_port
 def http(self,port,path,body=None):
  c=http.client.HTTPConnection('127.0.0.1',port,timeout=4)
  try:
   c.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body));r=c.getresponse();return r.status,json.loads(r.read())
  finally:c.close()


 def request(self,tenant='studio',report='weekly'):return self.command('request',{'tenant':tenant,'report':report})['outcome']
 def claim(self):return self.command('claim')['outcome']
 def finish(self,claim):return self.command('finish',{'jobId':claim['jobId'],'lease':claim['lease']})['outcome']
 def test_concurrent_identical_report_coalesces_before_and_after_cache(self):
  with concurrent.futures.ThreadPoolExecutor(2) as pool:
   rows=list(pool.map(lambda owner:self.command('request',{'tenant':'studio','report':'weekly'},owner)['outcome'],[self.a,self.b]))
  self.assertEqual(rows[0]['jobId'],rows[1]['jobId']);self.assertEqual(1,len(self.view()['jobs']))
  claim=self.claim();self.finish(claim);cached=self.request();self.assertTrue(cached['cached']);self.assertEqual(claim['jobId'],cached['jobId'])
 def test_capacity_refusal_is_durable_and_new_identity_can_retry_after_release(self):
  for tenant in ('studio','garden'):
   for report in ('weekly','monthly'):self.request(tenant,report)
  body=self.body('request',{'tenant':'market','report':'weekly'});refusal=self.run_command(body)
  self.assertFalse(refusal['outcome']['accepted']);self.assertEqual(2000,refusal['outcome']['retryAfterMs'])
  self.finish(self.claim());self.assertEqual(refusal,self.run_command(body,self.b));self.assertTrue(self.request('market')['accepted'])
 def test_per_tenant_limit_is_independent_from_total_queue_limit(self):
  self.request();self.request(report='monthly');self.command('source')
  self.assertFalse(self.request()['accepted']);self.assertTrue(self.request('garden')['accepted'])
 def test_fifo_and_single_worker_admission(self):
  first=self.request('garden','monthly');second=self.request('studio','weekly');claim=self.claim()
  self.assertEqual(first['jobId'],claim['jobId']);self.assertFalse(self.claim()['accepted']);self.finish(claim)
  self.assertEqual(second['jobId'],self.claim()['jobId'])
 def test_exact_lease_deadline_rejects_completion_and_new_lease_fences_old_worker(self):
  self.request();old=self.claim();self.now[0]+=10_000
  self.assertFalse(self.finish(old)['accepted']);new=self.claim();self.assertEqual(old['lease']+1,new['lease']);self.assertEqual(old['jobId'],new['jobId'])
  self.assertFalse(self.finish(old)['accepted']);self.assertTrue(self.finish(new)['accepted']);self.assertEqual('COMPLETE',self.view()['jobs'][0]['status'])
 def test_old_version_worker_populates_only_its_version_key(self):
  old=self.request();claim=self.claim();self.command('source');new=self.request();self.assertNotEqual(old['jobId'],new['jobId'])
  self.finish(claim);view=self.view();self.assertIn('studio:weekly:1',view['cache']);self.assertNotIn('studio:weekly:2',view['cache'])
  self.assertEqual(new['jobId'],self.request()['jobId']);self.assertEqual(1,view['jobs'][0]['sourceVersion'])
 def test_lost_request_reply_recovers_one_job_and_historical_lease_never_changes(self):
  port=self.serve();body=self.body('request',{'tenant':'studio','report':'weekly'});self.http(port,'/__control',{'drop_reply':True})
  with self.assertRaises(http.client.RemoteDisconnected):self.http(port,'/commands',body)
  self.http(port,'/__control',{});restored=Service(self.database);receipt=self.run_command(body,restored);self.assertEqual(1,len(self.view()['jobs']))
  claimbody=self.body('claim');old=self.run_command(claimbody);self.now[0]+=10_000;self.claim()
  self.assertEqual(old,self.run_command(claimbody));self.assertEqual(2,self.view()['jobs'][0]['lease']);self.assertEqual(receipt,self.run_command(body))
 def test_wrong_scope_lease_type_and_changed_payload_never_admit(self):
  with self.assertRaises(Problem):self.request('unknown')
  self.request();claim=self.claim()
  with self.assertRaises(Problem):self.command('finish',{'jobId':claim['jobId'],'lease':True})
  body=self.body('request',{'tenant':'garden','report':'weekly'});self.run_command(body)
  with self.assertRaises(Problem):self.run_command(body|{'args':{'tenant':'market','report':'weekly'}})
  self.assertEqual(2,len(self.view()['jobs']))
 def test_observed_expiry_cannot_revive_the_same_worker_after_clock_rollback(self):
  self.request();old=self.claim();self.now[0]+=10000
  self.assertFalse(self.finish(old)['accepted'])
  self.now[0]-=10000
  self.assertFalse(self.finish(old)['accepted'])
  new=self.claim();self.assertEqual(old['lease']+1,new['lease'])
  self.assertTrue(self.finish(new)['accepted'])
  self.request('garden');next_job=self.claim();self.now[0]+=10000
  observed=self.view();self.assertEqual('QUEUED',next(j for j in observed['jobs'] if j['id']==next_job['jobId'])['status'])
  self.now[0]-=10000
  restored=Service(self.database,clock=lambda:self.now[0])
  self.assertFalse(self.command('finish',{'jobId':next_job['jobId'],'lease':next_job['lease']},restored)['outcome']['accepted'])

if __name__=='__main__':unittest.main()
