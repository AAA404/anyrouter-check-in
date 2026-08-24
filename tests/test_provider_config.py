import json

from utils.config import AppConfig, ProviderConfig, load_accounts_config


def test_builtin_provider_profile_persistence_defaults(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)

	config = AppConfig.load_from_env()

	assert config.providers['anyrouter'].persist_profile is True
	assert config.providers['agentrouter'].persist_profile is False


def test_provider_profile_persistence_can_override_builtin(monkeypatch):
	monkeypatch.setenv(
		'PROVIDERS',
		json.dumps(
			{
				'anyrouter': {'domain': 'https://anyrouter.top', 'persist_profile': False},
				'agentrouter': {'domain': 'https://agentrouter.org', 'persist_profile': True},
			}
		),
	)

	config = AppConfig.load_from_env()

	assert config.providers['anyrouter'].persist_profile is False
	assert config.providers['agentrouter'].persist_profile is True


def test_agentrouter_domain_override_has_priority_over_providers(monkeypatch):
	monkeypatch.setenv(
		'PROVIDERS',
		json.dumps({'agentrouter': {'domain': 'https://agentrouter.org', 'use_proxy': True}}),
	)
	monkeypatch.setenv('AGENTROUTER_DOMAIN', 'https://ps.air-outer.com/')

	config = AppConfig.load_from_env()

	assert config.providers['agentrouter'].domain == 'https://ps.air-outer.com'


def test_custom_provider_profile_persistence_defaults_to_false(monkeypatch):
	monkeypatch.setenv('PROVIDERS', json.dumps({'custom': {'domain': 'https://custom.example.com'}}))

	config = AppConfig.load_from_env()

	assert config.providers['custom'].persist_profile is False


def test_provider_from_dict_inherits_profile_persistence_from_defaults():
	defaults = ProviderConfig(name='custom', domain='https://old.example.com', persist_profile=True)

	provider = ProviderConfig.from_dict(
		'custom',
		{'domain': 'https://new.example.com'},
		defaults=defaults,
	)

	assert provider.persist_profile is True


def test_github_cookies_account_does_not_require_api_user(monkeypatch):
	monkeypatch.setenv(
		'ANYROUTER_ACCOUNTS',
		json.dumps(
			[
				{
					'name': 'AgentRouter OAuth',
					'provider': 'agentrouter',
					'github_cookies': [{'name': 'user_session', 'value': 'redacted', 'domain': '.github.com'}],
				}
			]
		),
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert accounts[0].has_github_cookies()
	assert accounts[0].api_user is None
