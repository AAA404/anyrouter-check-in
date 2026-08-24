import httpx
import pytest

from checkin import add_github_cookies, check_in_account, parse_github_cookies, user_info_from_browser_profile
from utils.browser import BrowserLoginResult, wait_for_session_cookie
from utils.config import AccountConfig, AppConfig, ProviderConfig
from utils.github_oauth import GitHubOAuthHTTPError, login_agentrouter_with_github_http
from utils.proxy import get_agentrouter_browser_proxy


def test_parse_github_cookies_strips_exporter_specific_fields():
	cookies = parse_github_cookies(
		[
			{
				'name': 'user_session',
				'value': 'secret',
				'domain': '.github.com',
				'path': '/',
				'expirationDate': 2_000_000_000,
				'sameSite': 'no_restriction',
				'secure': True,
			},
			{'name': 'unrelated', 'value': 'ignored', 'domain': '.example.com'},
		]
	)

	assert cookies == [
		{
			'name': 'user_session',
			'value': 'secret',
			'domain': '.github.com',
			'path': '/',
		}
	]


def test_parse_github_cookies_supports_cookie_header_string():
	cookies = parse_github_cookies('user_session=abc; logged_in=yes')

	assert cookies == [
		{'name': 'user_session', 'value': 'abc', 'domain': '.github.com', 'path': '/'},
		{'name': 'logged_in', 'value': 'yes', 'domain': '.github.com', 'path': '/'},
	]


def test_parse_github_host_cookie_uses_host_only_url():
	cookies = parse_github_cookies(
		[{'name': '__Host-user_session_same_site', 'value': 'abc', 'domain': '.github.com', 'path': '/'}]
	)

	assert cookies == [
		{
			'name': '__Host-user_session_same_site',
			'value': 'abc',
			'url': 'https://github.com/',
			'secure': True,
		}
	]


def test_agentrouter_browser_proxy_uses_socks_for_local_mixed_port(monkeypatch):
	monkeypatch.setenv('CHECKIN_PROXY_URL', 'http://127.0.0.1:7890')

	assert get_agentrouter_browser_proxy() == {'server': 'socks5://127.0.0.1:7890'}


def test_agentrouter_http_oauth_completes_public_flow(monkeypatch):
	requests = []

	class FakeClient:
		created = 0

		def __init__(self, **_kwargs):
			self.kind = 'agentrouter' if FakeClient.created == 0 else 'github'
			FakeClient.created += 1
			self.cookies = httpx.Cookies()

		def __enter__(self):
			return self

		def __exit__(self, *_args):
			return None

		def post(self, url, *, data=None, headers=None):
			requests.append((self.kind, url, data))
			request = httpx.Request('POST', url, headers=headers)
			assert data == {'authenticity_token': 'csrf-token', 'authorize': '1'}
			return httpx.Response(
				302,
				headers={'location': 'https://ps.air-outer.com/oauth/github?code=oauth-code&state=signed-state'},
				request=request,
			)

		def get(self, url, *, headers=None, params=None):
			requests.append((self.kind, url, params))
			request_url = httpx.URL(url, params=params) if params else httpx.URL(url)
			request = httpx.Request('GET', request_url, headers=headers)
			if self.kind == 'github':
				assert self.cookies.get('user_session', domain='github.com') == 'secret'
				return httpx.Response(
					200,
					text=(
						'<form method="post" action="/login/oauth/authorize">'
						'<input name="authenticity_token" value="csrf-token">'
						'<button name="authorize" value="1">Authorize</button>'
						'</form>'
					),
					request=request,
				)
			if request_url.path == '/api/status':
				return httpx.Response(
					200,
					json={'success': True, 'data': {'github_client_id': 'client-id'}},
					request=request,
				)
			if request_url.path == '/api/oauth/state':
				self.cookies.set('session', 'state-session', domain='ps.air-outer.com', path='/')
				return httpx.Response(200, json={'success': True, 'data': 'signed-state'}, request=request)
			if request_url.path == '/api/oauth/github':
				assert params == {'code': 'oauth-code', 'state': 'signed-state', 'mode': 'login'}
				self.cookies.set('session', 'login-session', domain='ps.air-outer.com', path='/')
				return httpx.Response(
					200,
					json={'success': True, 'data': {'id': 123, 'quota': 12_500_000, 'used_quota': 500_000}},
					request=request,
				)
			if request_url.path == '/api/user/self':
				return httpx.Response(
					200,
					json={'success': True, 'data': {'id': 123, 'quota': 12_500_000, 'used_quota': 500_000}},
					request=request,
				)
			raise AssertionError(f'Unexpected request: {request_url}')

	monkeypatch.setattr('utils.github_oauth.httpx.Client', FakeClient)

	result = login_agentrouter_with_github_http(
		'https://ps.air-outer.com',
		'/api/user/self',
		[{'name': 'user_session', 'value': 'secret', 'domain': '.github.com', 'path': '/'}],
		proxy_url='http://127.0.0.1:7890',
	)

	assert result.user_profile['id'] == 123
	assert result.cookies['session'] == 'login-session'
	assert any(kind == 'github' and 'client_id=client-id' in url for kind, url, _params in requests)


def test_agentrouter_http_oauth_rejects_github_login_page(monkeypatch):
	class FakeClient:
		created = 0

		def __init__(self, **_kwargs):
			self.kind = 'agentrouter' if FakeClient.created == 0 else 'github'
			FakeClient.created += 1
			self.cookies = httpx.Cookies()

		def __enter__(self):
			return self

		def __exit__(self, *_args):
			return None

		def get(self, url, *, headers=None, params=None):
			request_url = httpx.URL(url, params=params) if params else httpx.URL(url)
			request = httpx.Request('GET', request_url, headers=headers)
			if self.kind == 'github':
				login_request = httpx.Request('GET', 'https://github.com/login?return_to=oauth')
				return httpx.Response(200, text='Sign in to GitHub', request=login_request)
			if request_url.path == '/api/status':
				return httpx.Response(
					200,
					json={'success': True, 'data': {'github_client_id': 'client-id'}},
					request=request,
				)
			return httpx.Response(200, json={'success': True, 'data': 'signed-state'}, request=request)

	monkeypatch.setattr('utils.github_oauth.httpx.Client', FakeClient)

	with pytest.raises(GitHubOAuthHTTPError, match='expired'):
		login_agentrouter_with_github_http(
			'https://ps.air-outer.com',
			'/api/user/self',
			[{'name': 'user_session', 'value': 'expired', 'domain': '.github.com', 'path': '/'}],
		)


@pytest.mark.asyncio
async def test_add_github_cookies_ignores_a_rejected_cookie(monkeypatch):
	class FakeContext:
		def __init__(self):
			self.added_names = []

		async def add_cookies(self, cookies):
			name = cookies[0]['name']
			if name == 'invalid':
				raise RuntimeError('Invalid cookie fields')
			self.added_names.append(name)

	context = FakeContext()
	monkeypatch.setattr('checkin.debug_print', lambda _message: None)

	success = await add_github_cookies(
		context,
		[
			{'name': 'user_session', 'value': 'secret', 'domain': '.github.com', 'path': '/'},
			{'name': 'invalid', 'value': 'bad', 'domain': '.github.com', 'path': '/'},
		],
		'AgentRouter GitHub',
	)

	assert success is True
	assert context.added_names == ['user_session']


def test_user_info_from_browser_profile_keeps_zero_balance():
	user_info = user_info_from_browser_profile({'quota': 0, 'used_quota': 0})

	assert user_info == {
		'success': True,
		'quota': 0.0,
		'used_quota': 0.0,
		'display': ':money: Current balance: $0.0, Used: $0.0',
	}


@pytest.mark.asyncio
async def test_wait_for_session_cookie_requires_new_value(monkeypatch):
	values = iter(['old', 'old', 'new'])

	class FakeContext:
		async def cookies(self, *_args):
			return [{'name': 'session', 'value': next(values)}]

	class FakePage:
		context = FakeContext()

	async def no_sleep(_seconds):
		return None

	monkeypatch.setattr('utils.browser.asyncio.sleep', no_sleep)

	assert await wait_for_session_cookie(
		FakePage(),
		1000,
		cookie_url='https://agentrouter.org',
		previous_value='old',
	)


@pytest.mark.asyncio
async def test_agentrouter_github_oauth_returns_browser_balance_without_httpx(monkeypatch):
	account = AccountConfig(
		cookies=None,
		provider='agentrouter',
		name='AgentRouter OAuth',
		github_cookies={'user_session': 'secret'},
	)
	provider = ProviderConfig(
		name='agentrouter',
		domain='https://agentrouter.org',
		sign_in_path=None,
		use_proxy=True,
	)
	login_result = BrowserLoginResult(
		cookies={'session': 'agentrouter-session'},
		api_user='123',
		user_profile={'id': 123, 'quota': 12_500_000, 'used_quota': 500_000},
	)

	async def fake_login(*_args, **_kwargs):
		return login_result

	def fail_httpx(*_args, **_kwargs):
		raise AssertionError('AgentRouter OAuth must not fall back to httpx check-in')

	monkeypatch.setattr('checkin.login_with_github_cookies', fake_login)
	monkeypatch.setattr('checkin.run_check_in_requests', fail_httpx)

	success, before, after = await check_in_account(account, 0, AppConfig(providers={'agentrouter': provider}))

	assert success is True
	assert before is None
	assert after == {
		'success': True,
		'quota': 25.0,
		'used_quota': 1.0,
		'display': ':money: Current balance: $25.0, Used: $1.0',
	}
