from pathlib import Path

import config


def test_pytest_data_dir_defaults_to_short_tmp_path():
    data_dir = config.get_data_dir()

    assert data_dir is not None
    path = Path(data_dir)
    assert str(path).startswith("/tmp/owt-")
    assert path.name.startswith("owt-")
    assert path != Path(config.default_data_dir())
