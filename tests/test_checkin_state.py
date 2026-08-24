import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from checkin import (
	format_check_in_notification,
	generate_balance_hash,
	load_balance_state,
	save_balance_state,
	user_info_from_balance_snapshot,
)


def test_balance_hash_changes_when_quota_changes():
	before = {'account_1': {'quota': 100.0, 'used': 20.0}}
	after = {'account_1': {'quota': 125.0, 'used': 20.0}}

	assert generate_balance_hash(before) != generate_balance_hash(after)


def test_balance_hash_changes_when_used_quota_changes():
	before = {'account_1': {'quota': 100.0, 'used': 20.0}}
	after = {'account_1': {'quota': 100.0, 'used': 21.0}}

	assert generate_balance_hash(before) != generate_balance_hash(after)


def test_balance_hash_is_stable_for_equivalent_balances():
	left = {
		'account_2': {'quota': 50.0, 'used': 1.0},
		'account_1': {'quota': 100.0, 'used': 20.0},
	}
	right = {
		'account_1': {'used': 20.0, 'quota': 100.0},
		'account_2': {'used': 1.0, 'quota': 50.0},
	}

	assert generate_balance_hash(left) == generate_balance_hash(right)


def test_balance_state_round_trip(tmp_path, monkeypatch):
	state_file = tmp_path / 'balance_state.json'
	monkeypatch.setattr('checkin.BALANCE_STATE_FILE', str(state_file))
	state = {'account_1': {'quota': 100.0, 'used': 20.0}}

	save_balance_state(state)

	assert load_balance_state() == state


def test_balance_snapshot_uses_dollar_values():
	assert user_info_from_balance_snapshot({'quota': 100.25, 'used': 20.5}) == {
		'success': True,
		'quota': 100.25,
		'used_quota': 20.5,
		'display': ':money: Current balance: $100.25, Used: $20.5',
	}


def test_first_balance_notification_shows_current_value():
	message = format_check_in_notification(
		{
			'name': 'AgentRouter GitHub',
			'before_quota': None,
			'before_used': None,
			'after_quota': 25.0,
			'after_used': 1.0,
			'check_in_reward': None,
			'usage_increase': None,
			'balance_change': None,
		}
	)

	assert '当前余额' in message
	assert '余额: $25.00  |  累计消耗: $1.00' in message


def test_balance_change_notification_shows_reward_usage_and_delta():
	message = format_check_in_notification(
		{
			'name': 'AgentRouter GitHub',
			'before_quota': 20.0,
			'before_used': 0.5,
			'after_quota': 24.0,
			'after_used': 1.5,
			'check_in_reward': 5.0,
			'usage_increase': 1.0,
			'balance_change': 4.0,
		}
	)

	assert '签到前' in message
	assert '签到后' in message
	assert '签到获得: +$5.00' in message
	assert '期间消耗: $1.00' in message
	assert '余额变化: +$4.00' in message
