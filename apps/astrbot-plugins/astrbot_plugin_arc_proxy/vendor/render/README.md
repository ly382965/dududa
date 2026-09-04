# ArcaeaChartRenderYurisaki vendor

Source: `project-yurisaki/ArcaeaChartRenderYurisaki` commit
`4da4266d7c7b5ba8eaab1900ce7cdfb06b74f0eb`.

The renderer and AFF parser are preserved from upstream. The only code-level
changes replace machine-specific theme paths with explicit configuration and
export that configuration alongside `Render`:

```python
from .vendor.render.ArcaeaChartRender import Render, configure_assets

configure_assets("/path/to/assets")
```

The asset root must contain the upstream `img`, `models`, and `Fonts` layout.
No game assets are included in this vendor directory. See `LICENSE` for the
upstream license. Runtime Python dependencies are listed in `requirements.txt`.
