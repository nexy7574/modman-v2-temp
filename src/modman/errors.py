import datetime


class Ratelimited(TimeoutError):
    """
    Raise when a request is ratelimited. It is up to the client to decide whether to wait out the limit, or exit.
    """

    def __init__(self, until: datetime.datetime):
        self.until = until
        super().__init__(f"Ratelimited until {until}")
