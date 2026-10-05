from tests.support.sensors.fixtures.unregistered_workflow import bar

_ = bar


def _lazy() -> None:
    from tests.support.sensors.fixtures.unregistered_workflow import side

    _ = side
