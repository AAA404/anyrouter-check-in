from pathlib import Path


def test_proxy_setup_probes_agentrouter_and_general_target():
	script = Path('scripts/setup_mihomo_proxy.sh').read_text(encoding='utf-8')

	assert 'PROXY_TEST_URLS' in script
	assert 'DIRECT_PROXY_URL="${CHECKIN_PROXY_URL:-}"' in script
	assert 'Validating directly configured CHECKIN_PROXY_URL' in script
	assert 'CHECKIN_PROXY_URL: ${{ secrets.CHECKIN_PROXY_URL }}' in Path('.github/workflows/checkin.yml').read_text(encoding='utf-8')
	assert '[[ ! "${http_code}" =~ ^[1-4][0-9][0-9]$ ]]' in script
	assert 'jq -e' in script
	assert '/api/oauth/state' in script
	assert 'type: select' in script
	assert 'PROXY_NAMES' in script
	assert 'http://127.0.0.1:9090/proxies/CHECKIN' in script
	assert 'providers/proxies/subscription' in script
	assert '.proxies[]?.name | select(. != "COMPATIBLE")' in script
	assert 'GROUP_NAMES' in script
	assert 'Waiting for CHECKIN proxy group' in script
	assert 'selected_node_index=-1' in script
	assert 'Testing proxy node' in script
