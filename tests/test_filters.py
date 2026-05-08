import pytest
from unittest.mock import MagicMock
from bot.filters import WhitelistFilter

def make_update(user_id: int):
    update = MagicMock()
    update.effective_user.id = user_id
    update.message = MagicMock()
    return update

def test_whitelist_allows_correct_user():
    f = WhitelistFilter(allowed_user_id=12345)
    update = make_update(user_id=12345)
    assert f.filter(update) is True

def test_whitelist_blocks_other_user():
    f = WhitelistFilter(allowed_user_id=12345)
    update = make_update(user_id=99999)
    assert f.filter(update) is False

def test_whitelist_blocks_no_user():
    f = WhitelistFilter(allowed_user_id=12345)
    update = MagicMock()
    update.effective_user = None
    assert f.filter(update) is False
