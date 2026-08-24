"""通过 HTTP 完成 AgentRouter 的 GitHub OAuth 登录。"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx

GITHUB_AUTHORIZE_URL = 'https://github.com/login/oauth/authorize'
# AgentRouter 官方前端公开的 OAuth App Client ID。/api/status 仅用于发现它，
# 但部分 Actions 出口会把该公开接口替换成 HTML，因此保留固定回退值。
DEFAULT_AGENTROUTER_GITHUB_CLIENT_ID = 'Ov23lidtiR4LeVZvVRNL'
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'


@dataclass
class GitHubOAuthHTTPResult:
	cookies: dict[str, str]
	user_profile: dict


class GitHubOAuthHTTPError(RuntimeError):
	"""HTTP OAuth 无法安全完成时抛出的可读错误。"""


class _AuthorizeFormParser(HTMLParser):
	"""提取 GitHub OAuth 确认页的 POST 表单。"""

	def __init__(self) -> None:
		super().__init__()
		self.form_action = ''
		self.form_method = 'post'
		self.fields: dict[str, str] = {}
		self._in_authorize_form = False

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		attributes = dict(attrs)
		if tag == 'form':
			action = attributes.get('action') or ''
			if '/login/oauth/authorize' in action:
				self.form_action = action
				self.form_method = (attributes.get('method') or 'post').lower()
				self._in_authorize_form = True
		elif tag in {'input', 'button'} and self._in_authorize_form:
			name = attributes.get('name')
			if name:
				self.fields[name] = attributes.get('value') or ''

	def handle_endtag(self, tag: str) -> None:
		if tag == 'form' and self._in_authorize_form:
			self._in_authorize_form = False


def _client_kwargs(proxy_url: str | None) -> dict:
	kwargs: dict = {
		'http2': True,
		'timeout': 30.0,
		'follow_redirects': False,
	}
	if proxy_url:
		kwargs['proxy'] = proxy_url
	return kwargs


def _json_data(response: httpx.Response, step: str) -> object:
	try:
		payload = response.json()
	except ValueError as exc:
		raise GitHubOAuthHTTPError(f'{step} returned invalid JSON (HTTP {response.status_code})') from exc
	if response.status_code != 200:
		raise GitHubOAuthHTTPError(f'{step} failed (HTTP {response.status_code})')
	if not isinstance(payload, dict) or payload.get('success') is not True:
		message = payload.get('message') if isinstance(payload, dict) else None
		raise GitHubOAuthHTTPError(f'{step} failed: {message or "unknown response"}')
	return payload.get('data')


def _github_cookie_domain(cookie: dict) -> str:
	domain = str(cookie.get('domain') or 'github.com').lstrip('.')
	return domain if domain == 'github.com' or domain.endswith('.github.com') else 'github.com'


def _add_github_cookies(client: httpx.Client, cookies: list[dict]) -> int:
	added = 0
	for cookie in cookies:
		name = cookie.get('name')
		value = cookie.get('value')
		if not name or value is None:
			continue
		client.cookies.set(
			str(name),
			str(value),
			domain=_github_cookie_domain(cookie),
			path=str(cookie.get('path') or '/'),
		)
		added += 1
	return added


def _is_github_url(url: str) -> bool:
	host = (urlparse(url).hostname or '').lower()
	return host == 'github.com' or host.endswith('.github.com')


def _extract_callback_params(callback_url: str, expected_state: str) -> tuple[str, str]:
	query = parse_qs(urlparse(callback_url).query)
	if query.get('error'):
		raise GitHubOAuthHTTPError(f'GitHub OAuth rejected the request: {query["error"][0]}')
	code = query.get('code', [''])[0]
	state = query.get('state', [''])[0]
	if not code:
		raise GitHubOAuthHTTPError('GitHub OAuth redirect did not include a code')
	if state != expected_state:
		raise GitHubOAuthHTTPError('GitHub OAuth state mismatch')
	return code, state


def _request_github_callback(
	client: httpx.Client,
	client_id: str,
	state: str,
	callback_host: str,
) -> tuple[str, str]:
	current_url = f'{GITHUB_AUTHORIZE_URL}?{urlencode({"client_id": client_id, "state": state, "scope": "user:email"})}'
	headers = {
		'User-Agent': USER_AGENT,
		'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
		'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
	}

	method = 'GET'
	form_data: dict[str, str] | None = None
	for _ in range(10):
		if method == 'POST':
			response = client.post(current_url, data=form_data or {}, headers={**headers, 'Referer': current_url})
		else:
			response = client.get(current_url, headers=headers)
		method = 'GET'
		form_data = None
		if response.status_code in REDIRECT_STATUS_CODES:
			location = response.headers.get('location')
			if not location:
				raise GitHubOAuthHTTPError('GitHub OAuth returned a redirect without Location')
			next_url = urljoin(current_url, location)
			if not _is_github_url(next_url):
				if (urlparse(next_url).hostname or '').lower() != callback_host:
					raise GitHubOAuthHTTPError('GitHub OAuth redirected to an unexpected callback host')
				return _extract_callback_params(next_url, state)
			current_url = next_url
			continue

		if response.status_code == 200:
			path = urlparse(str(response.url)).path
			if path == '/login':
				raise GitHubOAuthHTTPError('GitHub cookies are expired or do not contain an authenticated session')
			parser = _AuthorizeFormParser()
			parser.feed(response.text)
			if parser.form_action:
				form_url = urljoin(str(response.url), parser.form_action)
				if not _is_github_url(form_url):
					raise GitHubOAuthHTTPError('GitHub OAuth confirmation form has an unexpected host')
				current_url = form_url
				method = parser.form_method.upper()
				form_data = parser.fields
				continue
			raise GitHubOAuthHTTPError(
				'GitHub requires an OAuth confirmation page; authorize AgentRouter once in GitHub, then export fresh cookies'
			)
		raise GitHubOAuthHTTPError(f'GitHub OAuth authorize failed (HTTP {response.status_code})')

	raise GitHubOAuthHTTPError('GitHub OAuth exceeded the redirect limit')


def login_agentrouter_with_github_http(
	domain: str,
	user_info_path: str,
	github_cookies: list[dict],
	*,
	proxy_url: str | None = None,
) -> GitHubOAuthHTTPResult:
	"""用两个隔离的 HTTP 会话完成 AgentRouter GitHub OAuth。"""
	domain = domain.rstrip('/')
	agent_headers = {
		'User-Agent': USER_AGENT,
		'Accept': 'application/json, text/plain, */*',
		'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
		'Referer': f'{domain}/login',
	}

	with httpx.Client(**_client_kwargs(proxy_url)) as agent_client:
		status_response = agent_client.get(f'{domain}/api/status', headers=agent_headers)
		try:
			status_data = _json_data(status_response, 'AgentRouter status request')
		except GitHubOAuthHTTPError as exc:
			print(f'[WARN] AgentRouter status discovery failed, using built-in public GitHub client id: {exc}')
			status_data = None
		client_id = status_data.get('github_client_id') if isinstance(status_data, dict) else None
		client_id = client_id or DEFAULT_AGENTROUTER_GITHUB_CLIENT_ID

		state_response = agent_client.get(f'{domain}/api/oauth/state?mode=login', headers=agent_headers)
		state = _json_data(state_response, 'AgentRouter OAuth state request')
		if not isinstance(state, str) or not state:
			raise GitHubOAuthHTTPError('AgentRouter returned an invalid OAuth state')

		with httpx.Client(**_client_kwargs(proxy_url)) as github_client:
			if not _add_github_cookies(github_client, github_cookies):
				raise GitHubOAuthHTTPError('No valid GitHub cookies were available for HTTP OAuth')
			code, callback_state = _request_github_callback(
				github_client,
				str(client_id),
				state,
				(urlparse(domain).hostname or '').lower(),
			)

		callback_response = agent_client.get(
			f'{domain}/api/oauth/github',
			params={'code': code, 'state': callback_state, 'mode': 'login'},
			headers=agent_headers,
		)
		callback_data = _json_data(callback_response, 'AgentRouter OAuth callback')

		profile_response = agent_client.get(f'{domain}{user_info_path}', headers=agent_headers)
		try:
			profile_data = _json_data(profile_response, 'AgentRouter user verification')
		except GitHubOAuthHTTPError:
			profile_data = callback_data
		if not isinstance(profile_data, dict) or not profile_data.get('id'):
			raise GitHubOAuthHTTPError('AgentRouter OAuth completed but returned no user profile')

		cookies = {cookie.name: cookie.value for cookie in agent_client.cookies.jar}
		return GitHubOAuthHTTPResult(cookies=cookies, user_profile=profile_data)
