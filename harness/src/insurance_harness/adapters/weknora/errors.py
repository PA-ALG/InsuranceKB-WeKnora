"""WeKnora 调用异常分型（spec S2.6；设计 001 §4）。

- ``WeKnoraTransientError``：5xx / 网络超时——可重试；
- ``WeKnoraClientError``：4xx——不重试，带状态码与响应体；
- ``WeKnoraParseFailed``：解析业务失败（parse_status=failed/cancelled）。
"""


class WeKnoraError(Exception):
    """所有 WeKnora 适配层异常的基类。"""


class WeKnoraTransientError(WeKnoraError):
    """可重试错误：HTTP 5xx 或网络层超时/传输失败。"""


class WeKnoraClientError(WeKnoraError):
    """不可重试错误：HTTP 4xx。保留状态码与响应体供上层定位。"""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"WeKnora returned {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class WeKnoraParseFailed(WeKnoraError):
    """文档解析以 failed/cancelled 终态结束。"""

    def __init__(self, knowledge_id: str, parse_status: str, error_message: str) -> None:
        super().__init__(
            f"knowledge {knowledge_id} parse ended with {parse_status}: {error_message}"
        )
        self.knowledge_id = knowledge_id
        self.parse_status = parse_status
        self.error_message = error_message
