import unittest
from experiment_safety import ExperimentGate, SafeExecutor, SafetyError, REFERENCE


class AdmissionTests(unittest.TestCase):
    def gate(self):
        self.now = 10.
        g = ExperimentGate('connection',lambda:self.now)
        g.authorize('connection','User explicitly confirmed clearance, homing path and physical power cut-off')
        return g

    def test_gate_is_closed_until_operator_authorizes_matching_connection(self):
        g=ExperimentGate('connection')
        with self.assertRaises(SafetyError):g.admit()
        with self.assertRaises(SafetyError):g.authorize('other','yes')

    def test_invalid_targets_cannot_reach_driver(self):
        g=self.gate()
        for target in [(307,307,338),(307,307,313),(307,308,307),(307,307,float('nan')),(307,307,True)]:
            with self.assertRaises(SafetyError):g.green_path(REFERENCE,{1:REFERENCE[1],2:target})
        self.assertTrue(g.green_path(REFERENCE,{1:REFERENCE[1],2:(307,307,312)}))

    def test_origin_and_nontarget_joints_are_checked(self):
        g=self.gate()
        with self.assertRaises(SafetyError):g.green_path({1:REFERENCE[1],2:(307,307,295)},REFERENCE)
        with self.assertRaises(SafetyError):g.green_path({1:(308,287,297),2:REFERENCE[2]},REFERENCE)

    def test_full_path_not_just_endpoint(self):
        g=self.gate()
        self.assertTrue(g.observer_path((0,164,120),(-5,164,120),('A','B-small')))
        with self.assertRaises(SafetyError):g.observer_path((-4,164,122),(0,164,125),('B-small','C-small'))
        with self.assertRaises(SafetyError):g.observer_path((0,164,120),(0,164,130),('A','C-wide'))
        with self.assertRaises(SafetyError):g.observer_path((0,164,120),(-5,164,120),('A','B-small'),7)

    def test_timeout_pause_retains_pending_and_cannot_auto_resume(self):
        g=self.gate(); g.begin('m1'); g.pause('ACK timed out')
        self.assertEqual(g.pending,'m1')
        with self.assertRaises(SafetyError):g.admit()
        with self.assertRaises(SafetyError):g.authorize('connection','old confirmation')
        with self.assertRaises(SafetyError):g.finish('m1','frame')

    def test_settling_spacing_and_budget(self):
        g=self.gate();g.begin('m1')
        with self.assertRaises(SafetyError):g.finish('wrong','frame')
        g.finish('m1','fresh-window')
        with self.assertRaises(SafetyError):g.admit()
        self.now+=2;g.admit()
        g.max_actions=1
        with self.assertRaises(SafetyError):g.admit()
        self.assertTrue(g.paused)

    def test_wrong_frequency_is_rejected_before_hardware_writes(self):
        pca=dict(address=79,prescale=5,mode1=33)
        with self.assertRaisesRegex(SafetyError,'prescale 121'):
            SafeExecutor.check_hardware('70af092aeee8',pca,{})

    def test_host_timeout_does_not_release_or_send_return_command(self):
        g=self.gate();calls=[];events=[]
        def rpc(command):
            calls.append(command)
            raise TimeoutError('ACK missing')
        ex=SafeExecutor(g,rpc,lambda event,**kw:events.append((event,kw)),REFERENCE)
        with self.assertRaises(TimeoutError):
            ex.green({1:REFERENCE[1],2:(307,307,312)},'trial',lambda _:None)
        self.assertEqual(len(calls),1)
        self.assertIn('d.run_segment',calls[0])
        self.assertTrue(g.paused)
        self.assertFalse(events[-1][1]['release_requested'])
        with self.assertRaises(SafetyError):ex.green(REFERENCE,'retry',lambda _:None)
        self.assertEqual(len(calls),1)

    def test_low_visual_quality_holds_without_confirming_settled(self):
        g=self.gate();calls=[]
        def rpc(command):
            calls.append(command)
            return dict(enabled=True,scheduled_busy=False,command_counts={1:REFERENCE[1],2:(307,307,312)})
        ex=SafeExecutor(g,rpc,lambda *a,**kw:None,REFERENCE)
        with self.assertRaisesRegex(SafetyError,'stationary'):
            ex.green({1:REFERENCE[1],2:(307,307,312)},'trial',lambda _:dict(stationary=False))
        self.assertEqual(len(calls),1)
        self.assertTrue(g.paused)
        self.assertEqual(g.pending,'trial')

    def test_invalid_target_never_calls_existing_driver(self):
        g=self.gate();calls=[]
        ex=SafeExecutor(g,lambda cmd:calls.append(cmd),lambda *a,**kw:None,REFERENCE)
        with self.assertRaises(SafetyError):ex.green({1:REFERENCE[1],2:(307,307,320)},'trial',lambda _:None)
        self.assertEqual(calls,[])


if __name__=='__main__':unittest.main()
