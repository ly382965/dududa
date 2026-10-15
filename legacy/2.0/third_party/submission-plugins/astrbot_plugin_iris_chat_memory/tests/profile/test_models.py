"""画像数据模型测试"""

from iris_memory.profile.models import (
    GroupProfile,
    UserProfile,
    profile_to_dict,
    dict_to_group_profile,
    dict_to_user_profile,
    merge_custom_fields,
    _find_similar_key,
)


class TestGroupProfile:
    """群聊画像数据模型测试"""

    def test_create_group_profile(self):
        """测试创建群聊画像"""
        profile = GroupProfile(group_id="group_123")

        assert profile.group_id == "group_123"
        assert profile.group_name == ""
        assert profile.version == 1
        assert profile.interests == []
        assert profile.atmosphere_tags == []

    def test_group_profile_with_data(self):
        """测试带数据的群聊画像"""
        profile = GroupProfile(
            group_id="group_123",
            group_name="技术交流群",
            interests=["技术", "AI"],
            atmosphere_tags=["轻松", "技术范"],
        )

        assert profile.group_name == "技术交流群"
        assert profile.interests == ["技术", "AI"]
        assert profile.atmosphere_tags == ["轻松", "技术范"]

    def test_profile_to_dict(self):
        """测试画像转字典"""
        profile = GroupProfile(group_id="group_123", group_name="测试群")

        data = profile_to_dict(profile)

        assert data["group_id"] == "group_123"
        assert data["group_name"] == "测试群"

    def test_dict_to_group_profile(self):
        """测试字典转群聊画像"""
        data = {
            "group_id": "group_123",
            "group_name": "测试群",
            "version": 2,
            "interests": ["技术"],
        }

        profile = dict_to_group_profile(data)

        assert profile.group_id == "group_123"
        assert profile.group_name == "测试群"
        assert profile.version == 2
        assert profile.interests == ["技术"]


class TestUserProfile:
    """用户画像数据模型测试"""

    def test_create_user_profile(self):
        """测试创建用户画像"""
        profile = UserProfile(user_id="user_456")

        assert profile.user_id == "user_456"
        assert profile.user_name == ""
        assert profile.version == 1
        assert profile.personality_tags == []
        assert profile.interests == []

    def test_user_profile_with_data(self):
        """测试带数据的用户画像"""
        profile = UserProfile(
            user_id="user_456",
            user_name="小明",
            personality_tags=["外向", "幽默"],
            interests=["编程", "游戏"],
        )

        assert profile.user_name == "小明"
        assert profile.personality_tags == ["外向", "幽默"]
        assert profile.interests == ["编程", "游戏"]

    def test_user_profile_to_dict(self):
        """测试用户画像转字典"""
        profile = UserProfile(user_id="user_456", user_name="小明")

        data = profile_to_dict(profile)

        assert data["user_id"] == "user_456"
        assert data["user_name"] == "小明"

    def test_dict_to_user_profile(self):
        """测试字典转用户画像"""
        data = {
            "user_id": "user_456",
            "user_name": "小明",
            "version": 3,
            "personality_tags": ["外向"],
        }

        profile = dict_to_user_profile(data)

        assert profile.user_id == "user_456"
        assert profile.user_name == "小明"
        assert profile.version == 3
        assert profile.personality_tags == ["外向"]


class TestFindSimilarKey:
    """_find_similar_key 测试"""

    def test_exact_match(self):
        result = _find_similar_key({"家乡": "北京"}, "家乡")
        assert result == "家乡"

    def test_similar_chinese_keys(self):
        result = _find_similar_key({"喜欢的食物": "火锅"}, "爱吃的食物")
        assert result == "喜欢的食物"

    def test_similar_english_keys(self):
        result = _find_similar_key({"favorite_food": "hotpot"}, "favorite_foods")
        assert result == "favorite_food"

    def test_substring_containment(self):
        result = _find_similar_key({"活跃时段": "晚上"}, "活跃时间")
        assert result == "活跃时段"

    def test_no_similar_key(self):
        result = _find_similar_key({"家乡": "北京"}, "宠物")
        assert result is None

    def test_empty_existing(self):
        result = _find_similar_key({}, "家乡")
        assert result is None

    def test_empty_new_key(self):
        result = _find_similar_key({"家乡": "北京"}, "")
        assert result is None

    def test_returns_best_match(self):
        existing = {"食物": "米饭", "喜欢的食物": "火锅"}
        result = _find_similar_key(existing, "爱吃的食物")
        assert result == "喜欢的食物"


class TestMergeCustomFields:
    """merge_custom_fields 测试"""

    def test_add_new_fields(self):
        existing = {"家乡": "北京"}
        new_fields = {"宠物": "猫"}
        merged, changed = merge_custom_fields(existing, new_fields)
        assert changed is True
        assert merged["家乡"] == "北京"
        assert merged["宠物"] == "猫"

    def test_no_change_when_empty_new(self):
        existing = {"家乡": "北京"}
        merged, changed = merge_custom_fields(existing, {})
        assert changed is False
        assert merged == existing

    def test_overwrite_existing_key_with_high_confidence(self):
        existing = {"家乡": "北京"}
        new_fields = {"家乡": "上海"}
        merged, changed = merge_custom_fields(existing, new_fields, confidence=0.9)
        assert changed is True
        assert merged["家乡"] == "上海"

    def test_no_overwrite_with_low_confidence(self):
        existing = {"家乡": "北京"}
        new_fields = {"家乡": "上海"}
        merged, changed = merge_custom_fields(existing, new_fields, confidence=0.3)
        assert changed is False
        assert merged["家乡"] == "北京"

    def test_merge_similar_key(self):
        existing = {"喜欢的食物": "火锅"}
        new_fields = {"爱吃的食物": "烤肉"}
        merged, changed = merge_custom_fields(existing, new_fields, confidence=0.9)
        assert changed is True
        assert "喜欢的食物" in merged
        assert "爱吃的食物" not in merged
        assert merged["喜欢的食物"] == "烤肉"

    def test_max_fields_limit(self):
        existing = {
            "家乡": "北京",
            "宠物": "猫",
            "职业": "工程师",
            "年龄": "25",
            "身高": "175",
        }
        new_fields = {"爱好": "游泳", "学历": "本科", "血型": "A", "星座": "天秤"}
        merged, changed = merge_custom_fields(existing, new_fields, max_fields=7)
        assert len(merged) == 7
        assert changed is True

    def test_skip_empty_key_or_value(self):
        existing = {"家乡": "北京"}
        new_fields = {"": "值", "宠物": ""}
        merged, changed = merge_custom_fields(existing, new_fields)
        assert changed is False
        assert len(merged) == 1

    def test_preserves_existing_when_no_new(self):
        existing = {"家乡": "北京", "宠物": "猫"}
        merged, changed = merge_custom_fields(existing, None)
        assert changed is False
        assert merged == existing

    def test_trimming_keeps_latest(self):
        existing = {
            "家乡": "北京",
            "宠物": "猫",
            "职业": "工程师",
            "年龄": "25",
            "身高": "175",
            "学历": "本科",
            "血型": "A",
            "星座": "天秤",
            "爱好": "游泳",
            "特长": "钢琴",
        }
        new_fields = {"方言": "粤语"}
        merged, changed = merge_custom_fields(existing, new_fields, max_fields=10)
        assert len(merged) == 10
        assert "方言" in merged
        assert "家乡" not in merged
