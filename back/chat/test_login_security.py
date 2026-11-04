import json
from datetime import timedelta
from unittest import mock

from axes.models import AccessAttempt
from captcha.models import CaptchaStore
from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from . import login_security as security
from .test_accounts import fake_db_session, fake_user


class LoginSecurityTests(TestCase):
    def setUp(self):
        patch = mock.patch('chat.accounts.db_session', fake_db_session)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch('chat.accounts.authenticate', return_value=None)
        self.authenticate = patch.start()
        self.addCleanup(patch.stop)
        self.challenge = None

    def post(self, payload=None, client=None, ip='192.0.2.10', agent='test-agent'):
        body = {'username': 'alice01', 'password': 'wrong'}
        if payload:
            body.update(payload)
        response = (client or self.client).post('/api/auth/login/', json.dumps(body), content_type='application/json', REMOTE_ADDR=ip, HTTP_USER_AGENT=agent)
        self.challenge = response.json().get('captcha')
        return response

    def solved(self):
        key = self.challenge['key']
        return {'captcha_key': key, 'captcha_value': CaptchaStore.objects.get(hashkey=key).response}

    def three_failures(self):
        for number in range(3):
            response = self.post()
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()['captcha_required'], number == 2)
        return response

    def five_failures(self):
        self.three_failures()
        self.assertEqual(self.post(self.solved()).status_code, 401)
        return self.post(self.solved())

    def count(self, username='alice01', ip='192.0.2.10'):
        return sum(AccessAttempt.objects.filter(username=username, ip_address=ip).values_list('failures_since_start', flat=True))

    def test_third_failure_immediately_returns_captcha_and_image_works(self):
        response = self.three_failures()
        self.assertEqual(response.json()['error'], security.LOGIN_FAILED)
        self.assertEqual(self.client.session['fail_count'], 3)
        image = self.client.get(self.challenge['image_url'])
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image['Content-Type'], 'image/png')
        self.assertEqual(self.authenticate.call_count, 3)

    def test_wrong_missing_and_foreign_captcha_do_not_authenticate_or_count(self):
        self.three_failures()
        old_key = self.challenge['key']
        response = self.post({'captcha_key': old_key, 'captcha_value': 'incorrect'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], security.CAPTCHA_ERROR)
        self.assertNotEqual(self.challenge['key'], old_key)
        self.assertFalse(CaptchaStore.objects.filter(hashkey=old_key).exists())
        for payload in ({}, {'captcha_key': 'foreign', 'captcha_value': 'x'}, {'captcha_key': [], 'captcha_value': 3}):
            self.assertEqual(self.post(payload).status_code, 400)
        self.assertEqual(self.count(), 3)
        self.assertEqual(self.client.session['fail_count'], 3)
        self.assertEqual(self.authenticate.call_count, 3)

    def test_failure_counts_and_captcha_notices_are_exact_through_six_failures(self):
        for number in range(1, 7):
            payload = self.solved() if number > 3 else {}
            response = self.post(payload)
            self.assertEqual(response.status_code, 401)
            data = response.json()
            self.assertEqual(data['error'], security.LOGIN_FAILED)
            self.assertEqual(data['failure_count'], number)
            self.assertEqual(data['captcha_remaining'], max(3-number, 0))
            expected = (f'로그인 {number}회 실패 · {3-number}회 더 실패하면 보안문자 확인이 필요합니다.'
                        if number < 3 else f'로그인 {number}회 실패 · 보안문자를 입력해 주세요.')
            self.assertEqual(data['failure_notice'], expected)
            self.assertEqual(data['captcha_required'], number >= 3)
            self.assertNotIn('Retry-After', response)
            self.assertNotIn('lockout_url', data)
            self.assertNotIn('잠금', data['failure_notice'])
        self.assertEqual(self.authenticate.call_count, 6)
        self.assertEqual(self.count(), 6)

    def test_six_failures_can_immediately_login_with_correct_captcha(self):
        self.five_failures()
        self.assertEqual(self.post(self.solved()).status_code, 401)
        self.authenticate.return_value = fake_user()
        self.assertEqual(self.post(self.solved()).status_code, 200)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.client.session['fail_count'], 0)
        self.assertEqual(self.authenticate.call_count, 7)

    def test_cookie_deletion_after_three_failures_still_requires_captcha(self):
        self.three_failures()
        self.authenticate.return_value = fake_user()
        self.client.cookies.clear()
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()['captcha_required'])
        self.assertEqual(self.authenticate.call_count, 3)
        self.assertEqual(self.count(), 3)

    def test_expired_captcha_is_replaced_without_authenticating(self):
        self.three_failures()
        answer = self.solved()
        CaptchaStore.objects.filter(hashkey=answer['captcha_key']).update(expiration=timezone.now()-timedelta(seconds=1))
        response = self.post(answer)
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(self.challenge['key'], answer['captcha_key'])
        self.assertEqual(self.authenticate.call_count, 3)
        self.assertEqual(self.count(), 3)

    def test_success_resets_axes_and_session_and_keeps_existing_user_session(self):
        self.three_failures()
        answer = self.solved()
        self.authenticate.return_value = fake_user()
        self.assertEqual(self.post(answer).status_code, 200)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.client.session['fail_count'], 0)
        self.assertEqual(self.client.session['user_id'], 7)
        self.assertEqual(self.client.get('/api/auth/me/').json()['user']['username'], 'alice01')
        self.assertEqual(self.client.post('/api/auth/logout/').status_code, 200)
        self.assertIsNone(self.client.get('/api/auth/me/').json()['user'])

    def test_old_failure_records_still_require_captcha_without_time_restriction(self):
        self.three_failures()
        AccessAttempt.objects.update(attempt_time=timezone.now()-timedelta(hours=1))
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.count(), 3)
        self.authenticate.return_value = fake_user()
        self.assertEqual(self.post(self.solved()).status_code, 200)

    def test_captcha_count_is_username_ip_combination_and_normalizes_username(self):
        self.five_failures()
        self.assertEqual(self.post({'username': '  ALICE01  '}).status_code, 400)
        self.assertEqual(self.count(), 5)
        self.assertEqual(self.post({'username': 'bob01'}).status_code, 401)
        self.assertEqual(self.post(ip='192.0.2.11').status_code, 401)
        self.assertEqual(self.count('bob01'), 1)
        self.assertEqual(self.count(ip='192.0.2.11'), 1)

    def test_required_fields_and_bad_json_never_count(self):
        for payload in ({'username': ''}, {'password': ''}):
            self.assertEqual(self.post(payload).status_code, 400)
        self.assertEqual(self.client.post('/api/auth/login/', '{', content_type='application/json').status_code, 400)
        self.authenticate.assert_not_called()
        self.assertEqual(AccessAttempt.objects.count(), 0)

    def test_user_agent_changes_do_not_bypass_username_ip_limit(self):
        for i in range(3):
            self.assertEqual(self.post(agent=f'agent-{i}').status_code, 401)
        self.assertEqual(self.post(self.solved(), agent='agent-3').status_code, 401)
        self.assertEqual(self.post(self.solved(), agent='agent-4').status_code, 401)
        self.assertEqual(self.count(), 5)

    def test_refresh_preserves_counts_and_new_challenge_is_valid(self):
        self.three_failures()
        old = self.challenge['key']
        response = self.client.post('/api/auth/captcha/', json.dumps({'username': 'alice01'}), content_type='application/json', REMOTE_ADDR='192.0.2.10')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()['captcha']['key'], old)
        self.assertEqual(self.count(), 3)
        self.assertEqual(self.authenticate.call_count, 3)

    def test_csrf_protects_both_endpoints(self):
        strict = Client(enforce_csrf_checks=True)
        for url in ('/api/auth/login/', '/api/auth/captcha/'):
            self.assertEqual(strict.post(url, json.dumps({'username': 'alice01', 'password': 'x'}), content_type='application/json').status_code, 403)
        self.authenticate.assert_not_called()

    def test_db_error_does_not_count_or_log_in(self):
        self.authenticate.side_effect = RuntimeError('private database detail')
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private', response.content.decode())
        self.assertEqual(self.count(), 0)
        self.assertNotIn('user_id', self.client.session)

    def test_old_lockout_url_redirects_to_login_instead_of_time_restriction(self):
        response = self.client.get('/auth/lockout/')
        self.assertRedirects(response, '/')
        self.assertNotIn('Retry-After', response)

    @override_settings(LOGIN_TRUSTED_PROXY_IPS=['127.0.0.1'])
    def test_ip_headers_are_only_trusted_from_explicit_proxy(self):
        from django.test import RequestFactory
        factory = RequestFactory()
        self.assertEqual(security.client_ip(factory.get('/', REMOTE_ADDR='192.0.2.10', HTTP_X_REAL_IP='198.51.100.1')), '192.0.2.10')
        self.assertEqual(security.client_ip(factory.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_REAL_IP='198.51.100.1')), '198.51.100.1')

    def test_previously_locked_record_does_not_block_backend_or_api(self):
        from axes.backends import AxesStandaloneBackend
        from axes.handlers.proxy import AxesProxyHandler
        from django.test import RequestFactory
        AccessAttempt.objects.create(username='alice01', ip_address='192.0.2.10', user_agent='old-agent',
            failures_since_start=7, get_data='', post_data='', http_accept='', path_info='/api/auth/login/')
        request = RequestFactory().post('/api/auth/login/', REMOTE_ADDR='192.0.2.10')
        credentials = {'username': 'alice01'}
        with override_settings(AXES_LOCK_OUT_AT_FAILURE=True):
            self.assertTrue(AxesProxyHandler.is_locked(request, credentials))
        self.assertFalse(AxesProxyHandler.is_locked(request, credentials))
        self.assertIsNone(AxesStandaloneBackend().authenticate(request=request, username='alice01', password='x'))
        self.authenticate.return_value = fake_user()
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['failure_count'], 7)
        self.authenticate.assert_not_called()
        self.assertEqual(self.post(self.solved()).status_code, 200)

    def test_success_resets_only_current_username_and_ip(self):
        self.three_failures()
        answer = self.solved()
        AccessAttempt.objects.create(username='bob01', ip_address='192.0.2.10', user_agent='other',
            failures_since_start=2, get_data='', post_data='', http_accept='', path_info='/api/auth/login/')
        self.authenticate.return_value = fake_user()
        self.assertEqual(self.post(answer).status_code, 200)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.count('bob01'), 2)

    def test_missing_input_and_wrong_captcha_after_six_failures_do_not_increment(self):
        self.five_failures()
        self.post(self.solved())
        response = self.post({'captcha_key': self.challenge['key'], 'captcha_value': 'wrong'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['failure_count'], 6)
        self.assertEqual(self.client.session['fail_count'], 6)
        self.assertEqual(self.post({'password': ''}).status_code, 400)
        self.assertEqual(self.count(), 6)
        self.assertEqual(self.authenticate.call_count, 6)
