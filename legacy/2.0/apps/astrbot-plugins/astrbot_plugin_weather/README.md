# 天气数据适配器

该插件把 `wttr.in` 的公开天气 JSON 转换为 Dududa 2.0 可消费的结构化
Source/Capability 结果。外部调用必须显式传入城市；结果包含天气事实、`provenance`
和 `fetched_at`，供 Runtime 的 Composer 决定最终表达。

## Dududa 2.0 边界

- 稳定 Provider ID：`plugin.weather`
- 建议 Capability ID：`weather.current.read.v1`
- 执行类型：受治理的只读 Agent Capability
- 外部副作用：仅 HTTPS 网络读取
- 默认模式：`off`
- 消息 handler：无
- 自动发送：无
- 插件内 Scheduler：无
- 群发现、群记录和 OneBot 直发：无

`WeatherCapabilityProvider` 实现 Dududa 2.0 的通用 `CapabilityProvider` Port，
`WttrWeatherSource` 是可替换、可独立测试的数据源 Adapter。安装或启用插件不会自行授予
Capability；生产环境仍需在主仓 Capability Catalog 中加入 definition，并由 Core Compose
显式注册 `plugin.weather` Provider factory。

## 调用与结果

Provider 的唯一业务参数是非空 `city`，例如 `合肥`、`广东梅州兴宁`。返回结果形状为：

```json
{
  "schema_version": 1,
  "city": "合肥",
  "location": {"name": "Hefei", "region": "Anhui", "country": "China"},
  "current": {
    "condition": "晴",
    "temperature_c": 28,
    "feels_like_c": 30,
    "humidity_percent": 65,
    "wind_direction": "NE",
    "wind_kph": 11,
    "wind_text": "东北风 11 km/h"
  },
  "today": {"date": "2026-08-31", "minimum_c": 22, "maximum_c": 31},
  "provenance": {
    "provider": "wttr.in",
    "source_url": "https://wttr.in/...?...",
    "retrieval": "public_https_json"
  },
  "fetched_at": "2026-08-31T08:00:00+00:00"
}
```

上游内容按不可信公开数据进入 Runtime，Provider 不替模型总结，也不决定 SHORT、MEDIUM
或 LONG 输出。

## 主动推送状态

本插件没有接入生产 Scheduler。未来若需要天气日报，应由 Dududa Durable Scheduler 产生
结构化 Trigger，由 Source/Capability Runtime 读取固定城市，再经过主动出站授权、预算和
Output Adapter 发送；不得在插件中恢复 APScheduler 或 `send_group_msg`。

## 验证

```bash
PYTHONPATH=packages/dududa-agent/src:apps/astrbot-plugins \
  uv run --with pytest python -m pytest -q tests/test_weather_plugin.py
```
