from copy import deepcopy

from logistika_bot.domain import place
from logistika_bot.telegram import METHODS


def sample(**changes):
    data = {"kind": "cargo", "origin": place("Toshkent"),
            "destinations": [place("Samarqand")], "vehicles": ["tent", "ref"],
            "description": "Qoplangan mahsulot", "capacity": "20 t, 96 m³",
            "price": "Kelishiladi", "phone": "+998000000000"}
    data.update(changes)
    return data


class FakeAPI:
    """Validates actual aiogram request models, without HTTP or real tokens."""

    def __init__(self):
        self.calls = []
        self.next_id = 100
        self.fail_send_at = None
        self.send_count = 0

    async def call(self, method: str, **params):
        METHODS[method].model_validate(params)
        if method == "sendMessage":
            self.send_count += 1
            if self.send_count == self.fail_send_at:
                raise RuntimeError("Simulated network interruption")
        self.calls.append((method, deepcopy(params)))
        self.next_id += 1
        return {"message_id": self.next_id} if method in {"sendMessage", "sendContact", "sendInvoice"} else True

    def buttons(self, prefix: str = ""):
        result = []
        for method, params in self.calls:
            for row in params.get("reply_markup", {}).get("inline_keyboard", []):
                for button in row:
                    if button.get("callback_data", "").startswith(prefix):
                        result.append(button)
        return result

    def text(self) -> str:
        return "\n".join(params.get("text", "") for _, params in self.calls)
