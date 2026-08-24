"""代理配置：读取环境变量并供浏览器 / HTTP 客户端使用。"""

from __future__ import annotations

import os


def get_proxy_server(*, use_proxy: bool = True) -> str | None:
	"""按平台配置读取 CHECKIN_PROXY_URL；use_proxy=False 时不返回代理地址。"""
	if not use_proxy:
		return None
	server = os.getenv('CHECKIN_PROXY_URL', '').strip()
	return server or None


def get_playwright_proxy(*, use_proxy: bool = True) -> dict[str, str] | None:
	server = get_proxy_server(use_proxy=use_proxy)
	if not server:
		return None
	return {'server': server}


def get_agentrouter_browser_proxy(*, use_proxy: bool = True) -> dict[str, str] | None:
	"""Return the AgentRouter browser proxy, preferring SOCKS for local mixed-port."""
	proxy = get_playwright_proxy(use_proxy=use_proxy)
	if not proxy:
		return None
	server = proxy['server']
	if server.startswith('http://127.0.0.1:'):
		proxy['server'] = f'socks5://{server.removeprefix("http://")}'
	return proxy
