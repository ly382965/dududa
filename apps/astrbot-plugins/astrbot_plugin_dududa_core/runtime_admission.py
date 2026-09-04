"""Count whole bridge calls, including delivery, for a scoped Runtime swap."""

from functools import wraps


def tracked_runtime_call(method):
    @wraps(method)
    async def tracked(self, *args, **kwargs):
        if getattr(self, "_configuration_paused", False):
            from .rollout_bridge import AstrBotRuntimePreviewError, _legacy

            if method.__name__ == "preview":
                raise AstrBotRuntimePreviewError("runtime_configuration_applying")
            # Suppress legacy ownership during the short controlled swap.
            from dataclasses import replace

            event = args[0] if args else kwargs.get("event")
            stop = getattr(event, "stop_event", None)
            if callable(stop):
                stop()
            result = _legacy("runtime_configuration_applying")
            return replace(result, legacy_owner=False, runtime_owner=True)
        self._active_configuration_calls = (
            getattr(self, "_active_configuration_calls", 0) + 1
        )
        try:
            return await method(self, *args, **kwargs)
        finally:
            self._active_configuration_calls -= 1

    return tracked
