from pathlib import Path


def test_proxy_setup_probes_agentrouter_and_general_target():
	script = Path('scripts/setup_mihomo_proxy.sh').read_text(encoding='utf-8')

	assert 'PROXY_TEST_URLS' in script
	assert '[[ ! "${http_code}" =~ ^[1-4][0-9][0-9]$ ]]' in script
