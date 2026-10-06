class Secret:
    """Holds a secret value. str() and repr() are always masked."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return "********"

    def __repr__(self) -> str:
        return "Secret('********')"

    def __bool__(self) -> bool:
        return bool(self._value)
