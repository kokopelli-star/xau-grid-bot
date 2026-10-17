"""All APIs here are fakes. Never imports or initializes native MetaTrader5."""
import ast
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from terminal_binding import TerminalSpec, TerminalBinding, BindingError
from terminal_process import choose_terminal, AttachmentUnavailable

VALUES = dict(terminal_exe_path=r'C:\OFFLINE_ONLY\terminal64.exe',
              terminal_data_path=r'C:\OFFLINE_ONLY\data', expected_account_login=123,
              expected_account_server='OFFLINE-ONLY')


def setup_guard():
    spec = TerminalSpec(VALUES)
    target = NS(pid=1,path=spec.exe,alive=lambda:True,close=Mock())
    api = Mock()
    api.terminal_info.return_value=NS(connected=True,path=spec.installation,data_path=spec.data,
                                    trade_allowed=True,tradeapi_disabled=False)
    api.order_send.return_value=NS(retcode=10009)
    api.account_info.return_value=NS(login=123,server='OFFLINE-ONLY',trade_allowed=True,trade_expert=True)
    return TerminalBinding(spec,target),api


class GuardTests(unittest.TestCase):
    def test_each_native_order_kind_validated_before_and_after(self):
        for action in ('DEAL-entry','DEAL-close','REMOVE','SLTP','PENDING'):
            with self.subTest(action=action):
                guard,api=setup_guard()
                self.assertIs(guard.send(api,{'action':action}),api.order_send.return_value)
                self.assertEqual(api.account_info.call_count,4)
                api.order_send.assert_called_once()

    def test_wrong_identity_disconnect_permissions_and_exit_latch(self):
        cases=[('terminal','path',r'C:\OTHER'),('terminal','data_path',r'C:\OTHER'),
               ('terminal','connected',False),('terminal','tradeapi_disabled',True),
               ('account','login',999),('account','server','OTHER'),('account','trade_allowed',False)]
        for entity,key,value in cases:
            with self.subTest(entity=entity,key=key):
                guard,api=setup_guard()
                obj=getattr(api,entity+'_info').return_value
                old=getattr(obj,key);setattr(obj,key,value)
                with self.assertRaises(BindingError):guard.send(api,{})
                setattr(obj,key,old)
                with self.assertRaises(BindingError):guard.send(api,{})
                api.order_send.assert_not_called()
        guard,api=setup_guard();guard.target.alive=lambda:False
        with self.assertRaises(BindingError):guard.send(api,{})
        api.order_send.assert_not_called()

    def test_switch_within_check_blocks_send(self):
        guard,api=setup_guard()
        good=api.account_info.return_value
        api.account_info.side_effect=[good,NS(login=999,server='OTHER')]
        with self.assertRaises(BindingError):guard.send(api,{})
        api.order_send.assert_not_called()

    def test_switch_during_send_is_unknown_and_cannot_retry(self):
        guard,api=setup_guard()
        def changed(request):
            api.account_info.return_value.login=999
            return NS(retcode=10009)
        api.order_send.side_effect=changed
        with self.assertRaisesRegex(BindingError,'unknown'):guard.send(api,{})
        api.account_info.return_value.login=123
        with self.assertRaises(BindingError):guard.send(api,{})
        api.order_send.assert_called_once()

    def test_native_send_exception_latches_without_raw_details(self):
        guard,api=setup_guard();api.order_send.side_effect=RuntimeError('PRIVATE_VALUE')
        with self.assertRaises(BindingError) as error:guard.send(api,{})
        self.assertNotIn('PRIVATE_VALUE',str(error.exception))
        self.assertTrue(guard.failed)

    def test_spec_requires_explicit_absolute_paths_and_account(self):
        for key,value in [('terminal_exe_path',None),('terminal_exe_path','terminal64.exe'),
                          ('terminal_data_path','relative'),('expected_account_login',True),
                          ('expected_account_server',''),('password','must-not-be-accepted')]:
            with self.subTest(key=key),self.assertRaises(BindingError):TerminalSpec({**VALUES,key:value})

    def test_multiple_installations_select_by_path_and_duplicate_path_reject(self):
        def target(pid,path):return NS(pid=pid,path=path,close=Mock())
        a=target(1,VALUES['terminal_exe_path']);b=target(2,r'C:\OTHER\terminal64.exe')
        self.assertIs(choose_terminal([a,b],expected_path=VALUES['terminal_exe_path']),a)
        b.close.assert_called_once()
        with self.assertRaises(AttachmentUnavailable):
            choose_terminal([target(1,a.path),target(2,a.path)],pid=1,expected_path=a.path)



class LegacyGuardIntegrationTests(unittest.TestCase):
    def manager(self):
        from executor import GridManager
        from state import GridState
        guard,api=setup_guard()
        return GridManager(GridState(),binding=guard),api

    def test_all_order_calls_use_single_guarded_send(self):
        # Structural regression: no new unguarded native send can be added to executor.
        tree=ast.parse(Path('executor.py').read_text())
        direct=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                and n.func.attr=='order_send']
        self.assertEqual(direct,[])
        self.assertEqual(sum(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='send'
                             and isinstance(n.func.value,ast.Name) and n.func.value.id=='self' for n in ast.walk(tree)),7)

    def test_guard_rejects_every_public_trade_entrypoint(self):
        from executor import GridManager
        methods=[('place_grid_orders',()),('close_all_positions',()),('handle_breakout_exit',(True,)),
                 ('check_and_execute_half_close',(100,)),('run_executor',()),('run_monitor',())]
        for method,args in methods:
            with self.subTest(method=method):
                manager,api=self.manager();api.account_info.return_value.login=999
                with patch('executor.mt5',api),self.assertRaises(BindingError):getattr(manager,method)(*args)
                api.order_send.assert_not_called()
                self.assertTrue(manager.binding.failed)

    def test_send_gate_applies_to_every_action_and_never_resets(self):
        for action in ('DEAL','REMOVE','SLTP','PENDING'):
            manager,api=self.manager()
            with patch('executor.mt5',api):
                manager.send({'action':action})
                api.terminal_info.return_value.data_path=r'C:\OTHER'
                with self.assertRaises(BindingError):manager.send({'action':action})
                api.order_send.assert_called_once()

    def test_worker_failure_latches_other_worker(self):
        manager,api=self.manager()
        manager.state.is_new_request=True
        with patch('executor.mt5',api),patch.object(manager,'close_all_positions',side_effect=RuntimeError('PRIVATE')):
            with self.assertRaises(BindingError):manager.run_executor()
            with self.assertRaises(BindingError):manager.run_monitor()
        api.order_send.assert_not_called()

    def test_main_requires_local_config_before_initialize(self):
        import main
        with patch.object(main.sys,'argv',['main.py']),patch.object(main.TerminalSpec,'load',side_effect=BindingError()),patch.object(main,'mt5') as api:
            self.assertEqual(main.main(),1)
            api.initialize.assert_not_called()

    def test_main_fixed_path_and_identity_guard_before_workers(self):
        import main
        guard,api=setup_guard();spec=guard.spec;target=guard.target
        api.initialize.return_value=True
        api.terminal_info.return_value.data_path=r'C:\OTHER'
        with patch.object(main.sys,'argv',['main.py']),patch.object(main.sys,'platform','win32'),patch.object(main.TerminalSpec,'load',return_value=spec),patch.object(main,'find_running_terminal',return_value=target),patch.object(main,'mt5',api),patch.object(main,'GridManager') as manager:
            self.assertEqual(main.main(),1)
            api.initialize.assert_called_once_with(spec.exe,timeout=10000)
            manager.assert_not_called();api.order_send.assert_not_called()

class ReadOnlyDiagnosticTests(unittest.TestCase):
    def test_explicit_attach_required_no_import_otherwise(self):
        import diagnose_terminal as d
        guard,api=setup_guard();importer=Mock(return_value=api)
        self.assertFalse(d.run(guard.spec,platform_name='win32',importer=importer)['matched'])
        importer.assert_not_called()

    def test_two_terminal_selector_and_private_result(self):
        import diagnose_terminal as d
        guard,api=setup_guard();api.initialize.return_value=True
        finder=Mock(return_value=guard.target)
        result=d.run(guard.spec,True,42,platform_name='win32',importer=lambda _:api,finder=finder)
        self.assertTrue(result['matched'])
        finder.assert_called_once_with(42,expected_path=guard.spec.exe)
        for value in (guard.spec.exe,guard.spec.data,guard.spec.server,str(guard.spec.login)):
            self.assertNotIn(value,json.dumps(result))
        api.order_send.assert_not_called();api.order_check.assert_not_called();api.login.assert_not_called()

    def test_wrong_terminal_is_anonymous_and_never_trades(self):
        import diagnose_terminal as d
        guard,api=setup_guard();api.initialize.return_value=True
        api.terminal_info.return_value.path=r'C:\OTHER'
        report=d.run(guard.spec,True,platform_name='win32',importer=lambda _:api,finder=lambda *a,**kw:guard.target)
        self.assertFalse(report['matched'])
        api.order_send.assert_not_called()

class UnknownLegacySendTests(unittest.TestCase):
    def test_none_timeout_rejection_stop_remaining_batch(self):
        from executor import GridManager
        from state import GridState
        for result in (None,NS(retcode=10012),NS(retcode=10006)):
            guard,api=setup_guard();api.order_send.return_value=result
            manager=GridManager(GridState(),binding=guard)
            with patch('executor.mt5',api):
                with self.assertRaises(BindingError):manager.send({'action':'PENDING'})
                with self.assertRaises(BindingError):manager.send({'action':'PENDING'})
            api.order_send.assert_called_once()

class ConcurrentLegacyStopTests(unittest.TestCase):
    def test_unknown_result_latches_before_other_worker_can_send(self):
        from executor import GridManager
        from state import GridState
        from concurrent.futures import ThreadPoolExecutor
        import threading
        guard,api=setup_guard();api.order_send.return_value=None
        manager=GridManager(GridState(),binding=guard)
        returned=threading.Event();release=threading.Event();second_started=threading.Event()
        original=guard.send
        def delayed(api,request):
            result=original(api,request)
            returned.set()
            if not release.wait(2):raise AssertionError('test barrier timeout')
            return result
        guard.send=delayed
        def attempt(second=False):
            if second:second_started.set()
            try:manager.send({'action':'PENDING'})
            except BindingError:return 'stopped'
            return 'sent'
        with patch('executor.mt5',api),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(attempt)
            try:
                self.assertTrue(returned.wait(2))
                second=pool.submit(attempt,True)
                self.assertTrue(second_started.wait(2))
            finally:release.set()
            self.assertEqual(first.result(timeout=2),'stopped')
            self.assertEqual(second.result(timeout=2),'stopped')
        api.order_send.assert_called_once()
