import sys
import types
import unittest
from unittest.mock import call, patch


fake_pytz = types.ModuleType('pytz')
fake_pytz.timezone = lambda _name: None
sys.modules['pytz'] = fake_pytz

fake_aes_help = types.ModuleType('util.aes_help')
fake_aes_help.encrypt_data = lambda *args: args[0]
fake_aes_help.decrypt_data = lambda *args: args[0]
sys.modules['util.aes_help'] = fake_aes_help

fake_zepp_helper = types.ModuleType('util.zepp_helper')
fake_zepp_helper.post_fake_brand_data = lambda *_args: (True, 'ok')
sys.modules['util.zepp_helper'] = fake_zepp_helper

fake_push_util = types.ModuleType('util.push_util')
fake_push_util.push_results = lambda *_args: None
sys.modules['util.push_util'] = fake_push_util

import main


class StepConfigTest(unittest.TestCase):
    def test_two_accounts_use_independent_ranges_and_strip_step_spaces(self):
        configs = main.parse_account_configs({
            'USER': 'A#B',
            'PWD': 'PA#PB',
            'MIN_STEP': '15000 # 5000',
            'MAX_STEP': '20000 # 10000',
        })

        self.assertEqual(configs, [
            ('A', 'PA', 15000, 20000),
            ('B', 'PB', 5000, 10000),
        ])

    def test_single_range_is_shared_by_all_accounts(self):
        configs = main.parse_account_configs({
            'USER': 'A#B',
            'PWD': 'PA#PB',
            'MIN_STEP': '15000',
            'MAX_STEP': '20000',
        })

        self.assertEqual(configs, [
            ('A', 'PA', 15000, 20000),
            ('B', 'PB', 15000, 20000),
        ])

    def test_three_accounts_use_ranges_by_index(self):
        configs = main.parse_account_configs({
            'USER': 'A#B#C',
            'PWD': 'PA#PB#PC',
            'MIN_STEP': '15000#5000#10000',
            'MAX_STEP': '20000#10000#16000',
        })

        self.assertEqual(configs, [
            ('A', 'PA', 15000, 20000),
            ('B', 'PB', 5000, 10000),
            ('C', 'PC', 10000, 16000),
        ])

    def test_step_count_must_match_account_count(self):
        with self.assertRaisesRegex(
                main.ConfigError, 'MIN_STEP 配置数量与账号数量不一致'):
            main.parse_account_configs({
                'USER': 'A#B',
                'PWD': 'PA#PB',
                'MIN_STEP': '15000#5000#3000',
                'MAX_STEP': '20000#10000',
            })

    def test_max_step_count_must_match_account_count(self):
        with self.assertRaisesRegex(
                main.ConfigError, 'MAX_STEP 配置数量与账号数量不一致'):
            main.parse_account_configs({
                'USER': 'A#B',
                'PWD': 'PA#PB',
                'MIN_STEP': '15000#5000',
                'MAX_STEP': '20000#10000#16000',
            })

    def test_password_count_must_match_account_count(self):
        with self.assertRaisesRegex(
                main.ConfigError, 'PWD 配置数量与账号数量不一致'):
            main.parse_account_configs({
                'USER': 'A#B',
                'PWD': 'PA',
                'MIN_STEP': '15000#5000',
                'MAX_STEP': '20000#10000',
            })

    def test_step_value_must_be_an_integer(self):
        with self.assertRaisesRegex(
                main.ConfigError, 'MIN_STEP 第2项必须是整数'):
            main.parse_account_configs({
                'USER': 'A#B',
                'PWD': 'PA#PB',
                'MIN_STEP': '15000#abc',
                'MAX_STEP': '20000#10000',
            })

    def test_minimum_cannot_exceed_maximum(self):
        with self.assertRaisesRegex(
                main.ConfigError,
                '第1个账号步数配置错误：MIN_STEP 不能大于 MAX_STEP'):
            main.parse_account_configs({
                'USER': 'A#B',
                'PWD': 'PA#PB',
                'MIN_STEP': '20000#5000',
                'MAX_STEP': '10000#10000',
            })

    def test_time_scaling_uses_each_account_range(self):
        self.assertEqual(
            main.get_min_max_by_time(15000, 20000, hour=11, minute=0),
            (7500, 10000),
        )
        self.assertEqual(
            main.get_min_max_by_time(5000, 10000, hour=22, minute=0),
            (5000, 10000),
        )

    def test_each_submission_generates_its_own_random_step(self):
        runner_a = main.MiMotionRunner.__new__(main.MiMotionRunner)
        runner_a.invalid = False
        runner_a.log_str = ''
        runner_a.user_id = 'user-a'
        runner_a.login = lambda: 'token-a'

        runner_b = main.MiMotionRunner.__new__(main.MiMotionRunner)
        runner_b.invalid = False
        runner_b.log_str = ''
        runner_b.user_id = 'user-b'
        runner_b.login = lambda: 'token-b'

        with patch.object(
                main.random, 'randint', side_effect=[18346, 7284]) as randint:
            with patch.object(
                    main.zeppHelper, 'post_fake_brand_data',
                    return_value=(True, 'ok')) as post_step:
                runner_a.login_and_post_step(15000, 20000)
                runner_b.login_and_post_step(5000, 10000)

        self.assertEqual(randint.call_args_list, [
            call(15000, 20000),
            call(5000, 10000),
        ])
        self.assertEqual(post_step.call_args_list, [
            call('18346', 'token-a', 'user-a'),
            call('7284', 'token-b', 'user-b'),
        ])

    def test_serial_and_concurrent_execution_pass_all_account_values(self):
        account_configs = [
            ('A', 'PA', 15000, 20000),
            ('B', 'PB', 5000, 10000),
        ]

        for use_concurrent in (False, True):
            calls = []

            def fake_run_single_account(*args):
                calls.append(args)
                return {'user': args[2], 'success': True, 'msg': 'ok'}

            with self.subTest(use_concurrent=use_concurrent):
                with patch.object(main, 'use_concurrent', use_concurrent,
                                  create=True), \
                        patch.object(main, 'sleep_seconds', 0, create=True), \
                        patch.object(main, 'encrypt_support', False,
                                     create=True), \
                        patch.object(main, 'push_config', None, create=True), \
                        patch.object(main, 'run_single_account',
                                     side_effect=fake_run_single_account), \
                        patch.object(main.push_util, 'push_results'):
                    main.execute(account_configs)

                expected_calls = [
                    (2, 0, 'A', 'PA', 15000, 20000),
                    (2, 1, 'B', 'PB', 5000, 10000),
                ]
                if use_concurrent:
                    self.assertCountEqual(calls, expected_calls)
                else:
                    self.assertEqual(calls, expected_calls)


if __name__ == '__main__':
    unittest.main()
