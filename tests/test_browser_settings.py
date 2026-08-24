import sys
from types import SimpleNamespace

import pytest

from utils.browser import launch_login_context, load_browser_login_settings


def test_browser_login_settings_records_profile_persistence(monkeypatch, tmp_path):
	monkeypatch.setenv('CHECKIN_BROWSER_PROFILE_DIR', str(tmp_path))

	settings = load_browser_login_settings('Account 1', 'agentrouter', persist_profile=False)

	assert settings.persist_profile is False
	assert settings.profile_dir == tmp_path / 'agentrouter' / 'Account 1'
	assert settings.use_cloakbrowser is False


def test_agentrouter_browser_settings_use_provider_overrides(monkeypatch):
	monkeypatch.setenv('CHECKIN_HEADLESS', 'false')
	monkeypatch.setenv('CHECKIN_HUMANIZE', 'true')
	monkeypatch.setenv('CHECKIN_HEADLESS_AGENTROUTER', 'true')
	monkeypatch.setenv('CHECKIN_HUMANIZE_AGENTROUTER', 'false')

	settings = load_browser_login_settings('AgentRouter', 'agentrouter', persist_profile=False)

	assert settings.headless is True
	assert settings.humanize is False
	assert settings.use_cloakbrowser is False


def test_non_agentrouter_browser_settings_keep_global_values(monkeypatch):
	monkeypatch.setenv('CHECKIN_HEADLESS', 'false')
	monkeypatch.setenv('CHECKIN_HUMANIZE', 'true')

	settings = load_browser_login_settings('AnyRouter', 'anyrouter', persist_profile=True)

	assert settings.headless is False
	assert settings.humanize is True
	assert settings.use_cloakbrowser is True


def test_agentrouter_humanize_is_opt_in(monkeypatch):
	monkeypatch.setenv('CHECKIN_HEADLESS', 'false')
	monkeypatch.delenv('CHECKIN_HUMANIZE_AGENTROUTER', raising=False)
	monkeypatch.delenv('CHECKIN_HEADLESS_AGENTROUTER', raising=False)

	settings = load_browser_login_settings('AgentRouter', 'agentrouter', persist_profile=False)

	assert settings.headless is True
	assert settings.humanize is False


@pytest.mark.asyncio
async def test_launch_login_context_uses_persistent_context_when_enabled(monkeypatch, tmp_path):
	calls = {}
	context = SimpleNamespace()

	async def fake_launch_persistent_context_async(profile_dir, **kwargs):
		calls['profile_dir'] = profile_dir
		calls['kwargs'] = kwargs
		return context

	monkeypatch.setitem(
		sys.modules,
		'cloakbrowser',
		SimpleNamespace(launch_persistent_context_async=fake_launch_persistent_context_async),
	)

	settings = load_browser_login_settings('Account 1', 'anyrouter', persist_profile=True)
	settings = settings.__class__(
		headless=settings.headless,
		humanize=False,
		wait_timeout_ms=settings.wait_timeout_ms,
		profile_dir=tmp_path / 'profiles' / 'anyrouter' / 'Account 1',
		cloakbrowser_binary_path=settings.cloakbrowser_binary_path,
		persist_profile=settings.persist_profile,
		use_cloakbrowser=True,
	)

	result = await launch_login_context(settings)

	assert result is context
	assert calls['profile_dir'] == str(settings.profile_dir)


@pytest.mark.asyncio
async def test_launch_login_context_closes_browser_for_ephemeral_context(monkeypatch, tmp_path):
	class FakeContext:
		def __init__(self):
			self.closed = False

		async def close(self):
			self.closed = True

	class FakeBrowser:
		def __init__(self):
			self.context = FakeContext()
			self.closed = False
			self.context_kwargs = {}
			self.launch_kwargs = {}

		async def new_context(self, **kwargs):
			self.context_kwargs = kwargs
			return self.context

		async def close(self):
			self.closed = True

	browser = FakeBrowser()

	async def fake_launch_async(**kwargs):
		browser.launch_kwargs = kwargs
		return browser

	monkeypatch.setitem(
		sys.modules,
		'cloakbrowser',
		SimpleNamespace(launch_async=fake_launch_async),
	)

	settings = load_browser_login_settings('Account 1', 'anyrouter', persist_profile=False)
	settings = settings.__class__(
		headless=settings.headless,
		humanize=False,
		wait_timeout_ms=settings.wait_timeout_ms,
		profile_dir=tmp_path / 'profiles' / 'anyrouter' / 'Account 1',
		cloakbrowser_binary_path=settings.cloakbrowser_binary_path,
		persist_profile=settings.persist_profile,
		use_cloakbrowser=True,
	)

	context = await launch_login_context(settings)
	await context.close()

	assert context.closed is True
	assert browser.closed is True
	assert not settings.profile_dir.exists()


@pytest.mark.asyncio
async def test_launch_login_context_uses_system_chrome_for_agentrouter(monkeypatch):
	class FakeContext:
		def __init__(self):
			self.closed = False

		async def close(self):
			self.closed = True

	class FakeBrowser:
		def __init__(self):
			self.context = FakeContext()
			self.closed = False
			self.context_kwargs = None

		async def new_context(self, **kwargs):
			self.context_kwargs = kwargs
			return self.context

		async def close(self):
			self.closed = True

	class FakeChromium:
		def __init__(self, browser):
			self.browser = browser
			self.launch_kwargs = None

		async def launch(self, **kwargs):
			self.launch_kwargs = kwargs
			return self.browser

	class FakePlaywright:
		def __init__(self, chromium):
			self.chromium = chromium
			self.stopped = False

		async def stop(self):
			self.stopped = True

	class FakePlaywrightStarter:
		def __init__(self, playwright):
			self.playwright = playwright

		async def start(self):
			return self.playwright

	browser = FakeBrowser()
	chromium = FakeChromium(browser)
	playwright = FakePlaywright(chromium)
	monkeypatch.setattr(
		'playwright.async_api.async_playwright',
		lambda: FakePlaywrightStarter(playwright),
	)
	monkeypatch.setattr('utils.browser._find_playwright_browser', lambda: '/usr/bin/google-chrome')
	monkeypatch.setenv('CHECKIN_PROXY_URL', 'http://127.0.0.1:7890')

	settings = load_browser_login_settings('AgentRouter', 'agentrouter', persist_profile=False)
	context = await launch_login_context(settings, use_proxy=True)
	await context.close()

	assert chromium.launch_kwargs == {
		'headless': True,
		'proxy': {'server': 'socks5://127.0.0.1:7890'},
		'executable_path': '/usr/bin/google-chrome',
		'args': ['--disable-quic'],
	}
	assert browser.context_kwargs == {'viewport': {'width': 1920, 'height': 1080}}
	assert browser.context.closed is True
	assert browser.closed is True
	assert playwright.stopped is True
