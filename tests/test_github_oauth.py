import pytest

from checkin import check_in_account, parse_github_cookies, user_info_from_browser_profile
from utils.browser import BrowserLoginResult, wait_for_session_cookie
from utils.config import AccountConfig, AppConfig, ProviderConfig


def test_parse_github_cookies_supports_cookie_editor_format():
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
			'expires': 2_000_000_000.0,
			'secure': True,
			'sameSite': 'None',
		}
	]


def test_parse_github_cookies_supports_cookie_header_string():
	cookies = parse_github_cookies('user_session=abc; logged_in=yes')

	assert cookies == [
		{'name': 'user_session', 'value': 'abc', 'domain': '.github.com', 'path': '/'},
		{'name': 'logged_in', 'value': 'yes', 'domain': '.github.com', 'path': '/'},
	]


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
