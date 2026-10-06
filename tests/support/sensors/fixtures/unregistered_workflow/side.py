def workflow(name: str):
    def decorator(fn):
        return fn

    return decorator


@workflow("side")
def create_side():
    return None
