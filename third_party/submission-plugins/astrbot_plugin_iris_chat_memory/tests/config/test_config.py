"""配置系统测试"""

from pathlib import Path
from iris_memory.config import Config, init_config, get_config
from iris_memory.config.hidden_config import HiddenConfigManager
from iris_memory.config.defaults import Defaults, HiddenConfig


class TestConfig:
    def test_get_flat_key(self, tmp_path: Path):
        astrbot_config = {
            "l1_buffer": {"enable": True, "max_tokens": 1000},
        }

        hidden_manager = HiddenConfigManager(
            tmp_path / "hidden_config.json", HiddenConfig()
        )
        defaults = Defaults()

        config = Config(astrbot_config, hidden_manager, defaults, tmp_path)

        assert config.get("l1_buffer.enable")

    def test_get_with_default(self, tmp_path: Path):
        astrbot_config = {}

        hidden_manager = HiddenConfigManager(
            tmp_path / "hidden_config.json", HiddenConfig()
        )
        defaults = Defaults()

        config = Config(astrbot_config, hidden_manager, defaults, tmp_path)

        assert config.get("nonexistent", "default") == "default"

    def test_set_hidden_config(self, tmp_path: Path):
        astrbot_config = {}

        hidden_manager = HiddenConfigManager(
            tmp_path / "hidden_config.json", HiddenConfig()
        )
        defaults = Defaults()

        config = Config(astrbot_config, hidden_manager, defaults, tmp_path)

        config.set_hidden("debug_mode", True)

        assert config.get("debug_mode")

    def test_config_priority(self, tmp_path: Path):
        astrbot_config = {
            "test_section": {"test_key": "user_value"},
        }

        hidden_manager = HiddenConfigManager(
            tmp_path / "hidden_config.json", HiddenConfig()
        )
        defaults = Defaults()

        config = Config(astrbot_config, hidden_manager, defaults, tmp_path)

        assert config.get("test_section.test_key") == "user_value"

        config.set_hidden("test_section.test_key", "hidden_value")
        assert config.get("test_section.test_key") == "user_value"

    def test_data_dir_property(self, tmp_path: Path):
        astrbot_config = {}

        hidden_manager = HiddenConfigManager(
            tmp_path / "hidden_config.json", HiddenConfig()
        )
        defaults = Defaults()

        config = Config(astrbot_config, hidden_manager, defaults, tmp_path)

        assert config.data_dir == tmp_path

    def test_on_config_change(self, tmp_path: Path):
        astrbot_config = {}

        hidden_manager = HiddenConfigManager(
            tmp_path / "hidden_config.json", HiddenConfig()
        )
        defaults = Defaults()

        config = Config(astrbot_config, hidden_manager, defaults, tmp_path)

        changes = []

        def on_change(key, old_value, new_value):
            changes.append((key, old_value, new_value))

        config.on_config_change(on_change)

        config.set_hidden("debug_mode", True)

        assert len(changes) == 1
        assert changes[0] == ("debug_mode", None, True)


class TestHiddenConfigManager:
    def test_get_set(self, tmp_path: Path):
        manager = HiddenConfigManager(tmp_path / "hidden_config.json", HiddenConfig())

        manager.set("test_key", "test_value")

        assert manager.get("test_key") == "test_value"

    def test_persistence(self, tmp_path: Path):
        config_path = tmp_path / "hidden_config.json"
        manager1 = HiddenConfigManager(config_path, HiddenConfig())
        manager1.set("test_key", "test_value")

        manager2 = HiddenConfigManager(config_path, HiddenConfig())
        assert manager2.get("test_key") == "test_value"

    def test_default_value(self, tmp_path: Path):
        manager = HiddenConfigManager(tmp_path / "hidden_config.json", HiddenConfig())

        assert manager.get("nonexistent") is None


def test_global_config(tmp_path: Path):
    astrbot_config = {
        "l1_buffer": {"enable": True},
    }

    init_config(astrbot_config, tmp_path)

    config = get_config()
    assert config is not None
    assert config.data_dir == tmp_path
